# Submission template. The base image has the competition package, agent_runner.py,
# websockets, numpy and Pillow. Build it once from the repo (see README.md).
FROM competition-base:latest

# Only if your detection needs more packages (torch, onnxruntime, ...):
#   COPY requirements.txt .
#   RUN pip install --no-cache-dir -r requirements.txt

# Everything your agent imports must be COPYed here.
COPY my_agent.py detection.py ./
# COPY weights.pt ./          # model file, if you have one

# agent_runner.py loads exactly one Agent subclass from this file.
ENTRYPOINT ["python", "agent_runner.py", "--file", "my_agent.py"]
