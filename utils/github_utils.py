from datetime import datetime
import os
from langchain.document_loaders import GitLoader
import json
import openai
import requests
from supabase.client import Client, create_client
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.text_splitter import CharacterTextSplitter
from langchain.vectorstores import SupabaseVectorStore
from langchain.document_loaders import TextLoader
import shutil
from env import (
    OPENAI_API_KEY,
    GITHUB_ACCESS_TOKEN,
    FIXTHISCHRIS_SUPABASE_URL,
    FIXTHISCHRIS_SUPABASE_SERVICE_ROLE_KEY,
)

from langchain import LLMChain
from langchain.embeddings.openai import OpenAIEmbeddings
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain.vectorstores import SupabaseVectorStore
from langchain.schema import SystemMessage
from langchain.chat_models import ChatOpenAI
from langchain.callbacks.manager import CallbackManager
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler

from utils.tiktoken_utils import num_tokens_from_string

openai.api_key = OPENAI_API_KEY
from env import GITHUB_ACCESS_TOKEN

if FIXTHISCHRIS_SUPABASE_URL is None:
    raise ValueError("FIXTHISCHRIS_SUPABASE_URL must be set")
if FIXTHISCHRIS_SUPABASE_SERVICE_ROLE_KEY is None:
    raise ValueError("FIXTHISCHRIS_SUPABASE_SERVICE_ROLE_KEY must be set")

print("Supabase URL:", FIXTHISCHRIS_SUPABASE_URL)

supabase: Client = create_client(
    FIXTHISCHRIS_SUPABASE_URL, FIXTHISCHRIS_SUPABASE_SERVICE_ROLE_KEY
)
embeddings = OpenAIEmbeddings()

vector_store = SupabaseVectorStore(
    supabase, embeddings, table_name="documents", query_name="match_documents"
)


USAGE_LIMIT = 5


class RepoNotFound(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.repo = args[0]

    def __str__(self) -> str:
        return super().__str__() + f"Repo {self.repo} not found"


class UsageLimitExceeded(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.repo = args[0]

    def __str__(self) -> str:
        return super().__str__() + f"Usage limit exceeded for repo {self.repo}"


def get_usage_limit(repo: str):
    result = (
        supabase.table("usage-limits")
        .select("number_of_times_used_today")
        .eq("repo", repo)
        .execute()
    )
    return result.data


def is_rate_limit_reached(repo: str) -> bool:
    if repo is None or repo.strip() == "":
        raise ValueError("Repository name must be provided.")

    usage_limit = get_usage_limit(repo)
    print("Usage limit:", usage_limit)
    if not usage_limit:
        insert_result = (
            supabase.table("usage-limits")
            .insert({"repo": repo, "number_of_times_used_today": 1})
            .execute()
        )

        if insert_result.data:
            print("Inserted repo into usage-limits table")
            return False
        else:
            raise Exception("Failed to insert repo into usage-limits table")

    usage_limit = usage_limit[0]
    return usage_limit["number_of_times_used_today"] >= USAGE_LIMIT


def increment_usage_limit(repo: str) -> int:
    if repo is None or repo.strip() == "":
        raise ValueError("Repository name must be provided.")

    usage_limit = get_usage_limit(repo)
    print("Usage limit:", usage_limit)

    if not usage_limit:
        raise Exception("Repository not found in usage-limits table")

    usage_limit = usage_limit[0]
    updated_count = usage_limit["number_of_times_used_today"] + 1
    update_result = (
        supabase.table("usage-limits")
        .update({"number_of_times_used_today": updated_count})
        .eq("repo", repo)
        .execute()
    )
    print("Updated Limit:", update_result)

    if not update_result.data:
        raise Exception("Failed to update usage-limits table")

    return updated_count


def reset_usage_limits():
    # Reset the number_of_times_used_today for all repos at the end of the day
    result = supabase.table('usage_limits').update({'number_of_times_used_today': 0}).execute()


def fetch_all_files_in_repo(owner, repo):
    default_branch = get_default_branch(owner, repo)

    if default_branch is None:
        return None

    base_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    response = requests.get(base_url, headers=headers)
    if response.status_code != 200:
        print(
            f"Error fetching tree for {owner}/{repo}. Status code: {response.status_code}"
        )
        return None

    tree = response.json()
    file_paths = [item["path"] for item in tree["tree"] if item["type"] == "blob"]

    return file_paths


def get_default_branch(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        repo_info = response.json()
        return repo_info.get("default_branch", "")
    else:
        print(f"Failed to fetch repository info | Status Code: {response.status_code}")
        return None


def create_embedding_of_repo(repo_url: str, default_branch: str):
    owner = repo_url.split("/")[3]
    repo_name = repo_url.split("/")[4].split(".git")[0]
    repo_url_with_token = repo_url.replace('https://', f'https://{GITHUB_ACCESS_TOKEN}@')
    loader = GitLoader(
        clone_url=repo_url_with_token,
        repo_path="repo",
        branch=default_branch,
        
    )

    loader.load()

    # configure these to fit your needs
    exclude_dir = [".git", "node_modules", "public", "assets"]
    exclude_files = ["package-lock.json", ".DS_Store"]
    exclude_extensions = [
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tiff",
        ".ico",
        ".svg",
        ".webp",
        ".mp3",
        ".wav",
    ]

    documents = []

    for dirpath, dirnames, filenames in os.walk("repo"):
        # skip directories in exclude_dir
        dirnames[:] = [d for d in dirnames if d not in exclude_dir]

        for file in filenames:
            _, file_extension = os.path.splitext(file)

            # skip files in exclude_files
            if file not in exclude_files and file_extension not in exclude_extensions:
                file_path = os.path.join(dirpath, file)
                loader = TextLoader(file_path, encoding="ISO-8859-1")
                documents.extend(loader.load())

    text_splitter = CharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
    docs = text_splitter.split_documents(documents)
    for doc in docs:
        doc.metadata["repo_url"] = repo_url
        doc.metadata["owner"] = owner
        doc.metadata["repo_name"] = repo_name
        doc.metadata["inserted_at"] = datetime.now().isoformat()
        source = doc.metadata["source"]
        cleaned_source = "/".join(source.split("/")[1:])
        doc.page_content = (
            "FILE NAME: "
            + cleaned_source
            + "\n###\n"
            + doc.page_content.replace("\u0000", "")
        )

    embeddings = OpenAIEmbeddings()

    vector_store = SupabaseVectorStore.from_documents(
        docs,
        embeddings,
        client=supabase,
        table_name="documents",
    )
    shutil.rmtree("repo")


def setup_repo(owner, repo_name):
    repo_url = f"https://github.com/{owner}/{repo_name}.git"

    default_branch = get_default_branch(owner, repo_name)

    if default_branch is None:
        # TODO: report proper error message
        default_branch = "main"

    # Query the table and filter based on the repo_url
    query = (
        supabase.table("documents")  # Replace with your table name
        .select("metadata")
        .contains("metadata", {"repo_url": repo_url})
        .limit(5)
    )
    query_res = query.execute()
    if len(query_res.data) == 0:
        create_embedding_of_repo(repo_url, default_branch)
    else:
        print("Repo already exists")


def run_query(query: str, owner: str, repo_name: str):
    setup_repo(owner, repo_name)
    matched_docs = vector_store.similarity_search(
        query, filter={"repo_name": repo_name}
    )

    code_str = ""
    MAX_TOKENS = 3500

    current_tokens = 0

    for doc in matched_docs:
        doc_content = doc.page_content + "\n\n"
        doc_tokens = num_tokens_from_string(doc_content)
        print(matched_docs.index(doc), doc_tokens)
        if current_tokens + doc_tokens < MAX_TOKENS:
            code_str += doc_content
            current_tokens += doc_tokens
        else:
            break  # stop adding more content if it exceeds the max token limit

    # print("\n\033[35m" + code_str + "\n\033[32m")

    template = """
    You are Codebase AI. You are a super intelligent AI that answers questions about code bases.

    You are:
    - helpful & friendly
    - good at answering complex questions in simple language
    - an expert in all programming languages
    - able to infer the intent of the user's question

    The user will ask a question about their codebase, and you will answer it.

    When the user asks their question, you will answer it by searching the codebase for the answer.
    
    Here is the user's question and code file(s) you found to answer the question:
    
    Question:
    {query}
    
    Code file(s):
    {code}
    
    [END OF CODE FILE(S)]w

    Now answer the question using the code file(s) above.
    """

    chat = ChatOpenAI(
        streaming=True,
        callback_manager=CallbackManager([StreamingStdOutCallbackHandler()]),
        verbose=True,
        temperature=0.5,
    )
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    chat_prompt = ChatPromptTemplate.from_messages([system_message_prompt])
    chain = LLMChain(llm=chat, prompt=chat_prompt)

    print("running chain...")
    ai_said = chain.run(code=code_str, query=query)
    print("chain output...")
    return ai_said


# print(
#     run_query(
#         "How can i filter metadata by using filter argument in vector_store.similarity_search",
#         "mckaywrigley",
#         "repo-chat",
#     )
# )
# setup_repo("mckaywrigley", "repo-chat")

# def get_files(owner, repo, file_paths):
#     url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_paths}"
#     headers = {
#         "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
#         "Accept": "application/vnd.github.v3+json",
#     }

# # Example usage
# owner = "vivasvan1"
# repo = "front_greenberg_hammed"
# file_paths = fetch_all_files_in_repo(owner, repo)
# if file_paths:
#     schema = {
#         "type": "object",
#         "properties": {"files": {"type": "array", "items": {"type": "string"}}},
#     }

#     prompt = """I will provide you a list of file names and a description of a bug i want you to guess top 5 files will be need to debug it

# List of files:"""

#     for path in file_paths:
#         prompt = prompt + path + "\n"

#     prompt = (
#         prompt
#         + """Bug:
# add link to blog for each stream #130

# outputs as JSON of format {"files":["file1","file2"]}
# """
#     )
#     response = openai.ChatCompletion.create(
#         model="gpt-3.5-turbo",
#         messages=[
#             {"role": "user", "content": prompt},
#         ],
#     )

#     try:
#         print(response.choices[0].message) # type: ignore
#         print(json.loads(response.choices[0].message.content)) # type: ignore
#     except Exception as error:
#         print(error)
