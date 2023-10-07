from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import openai
import requests
import os
import logging

from env import OPENAI_API_KEY, GITHUB_ACCESS_TOKEN
from utils.github_utils import (
    USAGE_LIMIT,
    increment_usage_limit,
    is_rate_limit_reached,
    reset_usage_limits,
    run_query,
)

app = Flask(__name__)

openai.api_key = OPENAI_API_KEY

# Initialize logging
logging.basicConfig(level=logging.INFO)

from commons import send_github_request


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
    invites = send_github_request(fetch_invites_url, "GET", headers)
    if invites:
        return invites.json()
    else:
        logging.error("Failed to fetch repository invitations")
        return None


def accept_repository_invitation(invitation_id):
    accept_url = f"https://api.github.com/user/repository_invitations/{invitation_id}"
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",  # Use the appropriate API version
    }
    response = send_github_request(accept_url, "PATCH", headers)
    return response


def accept_github_invitations():
    repository_invites = fetch_repository_invites()

    if not repository_invites:
        return

    for invite in repository_invites:
        invitation_id = invite.get("id")
        response = accept_repository_invitation(invitation_id)

        if not response:
            continue

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
    notifications = send_github_request(notifications_url, "GET", headers)
    if not notifications:
        print("Failed to fetch notifications")
        return []

    notifications = notifications.json()
    unread_mentions = [
        notification
        for notification in notifications
        if (("mention" in notification["reason"]) and notification["unread"])
    ]
    return unread_mentions


def mark_issue_notification_as_read(id, issue_number):
    mark_as_read_url = f"https://api.github.com/notifications/threads/{id}"
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    response = send_github_request(mark_as_read_url, "PATCH", headers)

    if response:
        print(f"Marked issue {issue_number} as read")
    else:
        print(f"Failed to mark issue {issue_number} as read")


def fetch_issue(repo_owner, repo_name, issue_number):
    fetch_issue_url = (
        f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues/{issue_number}"
    )
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    issue_data = send_github_request(fetch_issue_url, "GET", headers)
    if issue_data:
        return issue_data.json()
    else:
        print(f"Failed to fetch issue #{issue_number}")
        return None


def fetch_issue_comments(comments_url):
    headers = {
        "Authorization": f"Bearer {GITHUB_ACCESS_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    comments = send_github_request(comments_url, "GET", headers)

    if not comments:
        print("Failed to fetch issue comments")
        return None

    comments = comments.json()
    if comments:
        print(f"Fetched {len(comments)} comments")
        return comments


def generate_gpt_prompt(issue_data):
    issue_title = issue_data.get("title")
    issue_body = issue_data.get("body")
    issue_comments_url = issue_data.get("comments_url")

    issue_comments_prompt = ""
    issue_comments = fetch_issue_comments(issue_comments_url)
    if issue_comments:
        for comment in issue_comments:
            if not (
                comment.get("user").get("login") == "fixThisChris"
                or comment.get("user").get("login") == "github-actions[bot]"
                or comment.get("user").get("login") == "dependabot[bot]"
            ):
                issue_comments_prompt += f"\nuser: {comment.get('user').get('login')} comment:{comment.get('body')}"

    gpt_prompt = f"Issue title: {issue_title}\nIssue Description: {issue_body}\n\n"
    if issue_comments_prompt != "":
        gpt_prompt += f"Issue Comments: {issue_comments_prompt}\n"

    return gpt_prompt


class FailedToFetchIssueException(Exception):
    pass


def solve_problem(mention, issue_number, issue_description):
    issue_data = fetch_issue(
        mention["repository"]["owner"]["login"],
        mention["repository"]["name"],
        issue_number,
    )

    if not issue_data:
        raise FailedToFetchIssueException()

    prompt = generate_gpt_prompt(issue_data)

    ai_response, patch_file = run_query(
        prompt,
        mention["repository"]["owner"]["login"],
        mention["repository"]["name"],
    )

    post_comment_to_issue(
        issue_number,
        ai_response,
        mention["repository"]["owner"]["login"],
        mention["repository"]["name"],
    )

    post_comment_to_issue(
        issue_number,
        patch_file,
        mention["repository"]["owner"]["login"],
        mention["repository"]["name"],
    )

    # Mark notification as read
    mark_issue_notification_as_read(mention["id"], issue_number)


def time_remaining_to_reset():
    # Get the current time
    now = datetime.now()

    # Construct a datetime object for the next midnight
    next_midnight = datetime(now.year, now.month, now.day) + timedelta(days=1)

    # Calculate the difference between the current time and the next midnight
    remaining_time = next_midnight - now

    # Return the remaining time as a timedelta object
    return remaining_time


def respond_to_unread_issues():
    unread_mentions = fetch_unread_mentions()
    # print(unread_mentions)

    for mention in unread_mentions:
        issue_number = mention["subject"]["url"].split("/")[-1]
        issue_description = mention["subject"]["title"]
        print(f"Issue {issue_number} is unread")

        rate_limit_exceeded = is_rate_limit_reached(mention["repository"]["name"])

        if not rate_limit_exceeded:
            try:
                solve_problem(mention, issue_number, issue_description)
                increment_usage_limit(mention["repository"]["name"])
            except FailedToFetchIssueException:
                continue
        else:
            remaining_time = time_remaining_to_reset()
            hours, remainder = divmod(remaining_time.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            print(f"Rate limit exceeded for {mention['repository']['name']}.")
            post_comment_to_issue(
                issue_number=issue_number,
                comment_text=f"""#### 🛑 **Rate Limit Exceeded!**
            
            ⌛ **Limit:** {USAGE_LIMIT} requests / day / repository
            🔒 **Refreshes In:** {int(hours)} hours, {int(minutes)} minutes
            
            <!-- To continue using the service, please consider upgrading to our **Pro Plan**.
            
            ##### 🚀 **Upgrade to Pro**
            Upgrade to the Pro Plan to enjoy enhanced access, faster response times, and priority support. Click [here](Upgrade_Link) to upgrade now! -->
            
            📬 For any inquiries for support or rate limit extension, please contact <a href="https://discord.gg/T6Hz6zpK7D" target="_blank">Support</a>.""",
                OWNER=mention["repository"]["owner"]["login"],
                REPO=mention["repository"]["name"],
            )

            # Mark notification as read
            mark_issue_notification_as_read(mention["id"], issue_number)


scheduler = BackgroundScheduler()
scheduler.add_job(func=accept_github_invitations, trigger="interval", seconds=30)
scheduler.add_job(func=respond_to_unread_issues, trigger="interval", seconds=30)


# Schedule the task to reset limits
scheduler.add_job(func=reset_usage_limits, trigger="cron", hour=0, minute=0)

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

#     return jsonify({"message": "Webhook processed successfully"})


def generate_response(prompt):
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "user", "content": prompt},
        ],
    )

    return completion.choices[0].message.content  # type: ignore


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
