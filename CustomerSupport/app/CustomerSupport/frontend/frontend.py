"""Flask frontend for the CustomerSupport AgentCore agent.

Authenticates against Cognito on startup (USER_PASSWORD_AUTH) and serves
a chat page where the browser talks directly to the AgentCore REST API.
"""

import json
import os
import uuid

import boto3
import requests
from flask import Flask, render_template, Response

REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))

app = Flask(__name__)

# Disable caching so Code Editor port proxy always serves fresh content
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def get_ssm_parameter(name: str) -> str:
    ssm = boto3.client("ssm", region_name=REGION)
    return ssm.get_parameter(Name=name)["Parameter"]["Value"]


def authenticate() -> str:
    """Authenticate against Cognito and return an access token."""
    pool_id = get_ssm_parameter("/app/customersupport/agentcore/pool_id")
    web_client_id = get_ssm_parameter("/app/customersupport/agentcore/web_client_id")
    region = pool_id.split("_")[0]

    client = boto3.client("cognito-idp", region_name=region)
    resp = client.initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH",
        ClientId=web_client_id,
        AuthParameters={
            "USERNAME": "workshopuser@example.com",
            "PASSWORD": "WorkshopPass1!",
        },
    )
    return resp["AuthenticationResult"]["AccessToken"]


def get_runtime_arn() -> str:
    """Resolve the CustomerSupport runtime ARN from CloudFormation outputs."""
    cf = boto3.client("cloudformation", region_name=REGION)
    stack_name = "AgentCore-CustomerSupport-default"
    resp = cf.describe_stacks(StackName=stack_name)
    outputs = resp["Stacks"][0]["Outputs"]
    for o in outputs:
        if "RuntimeArn" in o["OutputKey"] and "CustomerSupport" in o["OutputKey"]:
            return o["OutputValue"]
    raise RuntimeError("Could not find CustomerSupport runtime ARN in stack outputs")


# --- Initialise on startup ---
print("Authenticating against Cognito...")
ACCESS_TOKEN = authenticate()
print(f"✅ Authenticated as workshopuser@example.com")

RUNTIME_ARN = get_runtime_arn()
print(f"Runtime ARN: {RUNTIME_ARN}")

REGION = RUNTIME_ARN.split(":")[3]  # use region from ARN
INVOKE_URL = (
    f"https://bedrock-agentcore.{REGION}.amazonaws.com"
    f"/runtimes/{requests.utils.quote(RUNTIME_ARN, safe='')}/invocations"
)


@app.route("/")
def index():
    return render_template(
        "index.html",
        access_token=ACCESS_TOKEN,
        runtime_arn=RUNTIME_ARN,
        invoke_url=INVOKE_URL,
        session_id=str(uuid.uuid4()),
    )


@app.route("/new-token")
def new_token():
    """Refresh the Cognito token (called when the token expires)."""
    global ACCESS_TOKEN
    ACCESS_TOKEN = authenticate()
    return {"token": ACCESS_TOKEN}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8501, debug=False)
