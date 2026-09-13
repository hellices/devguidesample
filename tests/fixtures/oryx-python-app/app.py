from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello():
    return "Hello from Oryx Python 3.11 build test"

if __name__ == "__main__":
    app.run()
