from flask import Flask, request, jsonify
import openai
import requests
import os
app = Flask(__name__)

# GitHub API authentication
GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")

# OpenAI API authentication
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

import time
import atexit

from apscheduler.schedulers.background import BackgroundScheduler

import requests


def fetch_repository_invites():
    fetch_invites_url = "https://api.github.com/user/repository_invitations"
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(fetch_invites_url, headers=headers)
    if response.status_code == 200:
        invites = response.json()
        return invites
    else:
        print("Failed to fetch repository invitations")
        return []


def accept_repository_invitation(invitation_id):
    accept_url = f"https://api.github.com/user/repository_invitations/{invitation_id}"
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",  # Use the appropriate API version
    }
    response = requests.patch(accept_url, headers=headers)
    return response


def accept_github_invitations():
    repository_invites = fetch_repository_invites()

    for invite in repository_invites:
        invitation_id = invite.get("id")
        response = accept_repository_invitation(invitation_id)
        if response.status_code == 204:
            print(f"Accepted repository invitation with ID {invitation_id}")
        else:
            print(f"Failed to accept repository invitation with ID {invitation_id}")
        time.sleep(1)


def fetch_unread_mentions():
    notifications_url = "https://api.github.com/notifications"
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(notifications_url, headers=headers)
    if response.status_code == 200:
        notifications = response.json()
        unread_mentions = [
            notification
            for notification in notifications
            if (("mention" in notification["reason"]) and notification["unread"])
        ]
        return unread_mentions
    else:
        print("Failed to fetch notifications")
        return []


def mark_issue_notification_as_read(id, issue_number):
    # Mark notification as read
    mark_as_read_url = f"https://api.github.com/notifications/threads/{id}"
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.patch(mark_as_read_url, headers=headers)
    if response.status_code == 205:
        print(f"Marked issue {issue_number} as read")
    else:
        print(
            f"Failed to mark issue {issue_number} as read | Status Code: {response.status_code}"
        )


def fetch_issue(repo_owner, repo_name, issue_number):
    print(f"Fetching issue #{issue_number} #{repo_owner}/{repo_name}")
    fetch_issue_url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues/{issue_number}"
    )
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(fetch_issue_url, headers=headers)

    if response.status_code == 200:
        issue_data = response.json()
        return issue_data
    else:
        print(f"Failed to fetch issue #{issue_number}")
        return None


def fetch_issue_comments(comments_url):
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = requests.get(comments_url, headers=headers)

    if response.status_code == 200:
        print(f"Fetched {len(response.json())} comments")
        comments = response.json()
        return comments
    else:
        print(f"Failed to fetch issue comments")
        return None


def generate_gpt_prompt(issue_data):
    issue_title = issue_data.get("title")
    issue_body = issue_data.get("body")
    issue_comments_url = issue_data.get("comments_url")

    issue_comments = fetch_issue_comments(issue_comments_url)

    issue_comments_prompt = ""
    for comment in issue_comments:
        issue_comments_prompt += (
            f"\nuser: {comment.get('user').get('login')} comment:{comment.get('body')}"
        )

    gpt_prompt = f"Issue title: {issue_title}\nIssue Description: {issue_body}\nIssue Comments: {issue_comments_prompt}"
    return gpt_prompt


def respond_to_unread_issues():
    unread_mentions = fetch_unread_mentions()

    for mention in unread_mentions:
        issue_number = mention["subject"]["url"].split("/")[-1]
        issue_description = mention["subject"]["title"]
        print(f"Issue {issue_number} is unread")

        issue_data = fetch_issue(
            mention["repository"]["owner"]["login"],
            mention["repository"]["name"],
            issue_number,
        )

        prompt = generate_gpt_prompt(issue_data)
        # print(prompt)
        # response = generate_response(issue_description)
        # print(response)
        # post_comment_to_issue(issue_number, response, "solveitjim", mention["repository"]["name"])

        # Mark notification as read
        # mark_issue_notification_as_read(mention['id'], issue_number)


scheduler = BackgroundScheduler()
scheduler.add_job(func=accept_github_invitations, trigger="interval", seconds=10)
scheduler.add_job(func=respond_to_unread_issues, trigger="interval", seconds=10)
scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())


# @app.route("/webhook", methods=["POST"])
# def webhook():
#     data = request.json

#     # Check if the comment mentions the AI keyword
#     if "@solveitjim" in data["comment"]["body"]:
#         issue_number = data["issue"]["number"]
#         problem_description = data["comment"]["body"].split("@solveitjim")[1].strip()

#         # Use ChatGPT to generate a response
#         response = generate_response(problem_description)

#         # Post the response as a comment on the issue
#         post_comment_to_issue(issue_number, response)

#     return jsonify({"message": "Webhook processed successfully"})


def generate_response(prompt):
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": prompt},
        ],
    )

    return completion.choices[0].message.content


def post_comment_to_issue(issue_number, comment_text, OWNER, REPO):
    headers = {
        "Authorization": f"token {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "body": comment_text,
    }
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{issue_number}/comments"
    response = requests.post(url, json=payload, headers=headers)
    return response.json()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
