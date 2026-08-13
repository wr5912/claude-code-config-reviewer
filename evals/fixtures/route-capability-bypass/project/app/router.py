import subprocess


def dispatch(route):
    if route["capability"] == "deploy":
        subprocess.run(["deploy-synthetic-service"], check=True)
