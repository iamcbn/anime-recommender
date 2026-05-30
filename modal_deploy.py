import modal
import sys


app = modal.App("anime-recommender-api")


# Define the container image for the deployment
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential", "libpq-dev", "libgomp1")
    .add_local_file("requirements.txt", "/requirements.txt", copy=True)
    .run_commands(
        "pip install -r /requirements.txt --extra-index-url https://download.pytorch.org/whl/cu118"
    )
    .add_local_dir("./backend", remote_path="/root/backend")
)

# Expose the FastAPI app via a Serverless ASGI endpoint
@app.function(
    image=image,
    secrets=[modal.Secret.from_name("anime-secret")], # Inject secrets from Modal Secret Store
    gpu="T4",     # Use a T4 GPU for inference
    # 10 minutes timeout
    timeout=600,
)
@modal.asgi_app()
def fastapi_app():
    sys.path.append("/root")
    
    from backend.main import app as web_app
    return web_app