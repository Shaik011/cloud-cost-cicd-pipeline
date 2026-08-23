from flask import Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Cloud Cost-Governed CI/CD Pipeline is live! v2."

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)