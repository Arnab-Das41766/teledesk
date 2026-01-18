from flask import Flask, send_from_directory

app = Flask(__name__, static_folder='.')

@app.route("/")
def index():
    return send_from_directory('.', 'index.html')

@app.route("/testlatest.py")
def download_script():
    return send_from_directory(".", "testlatest.exe", as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
