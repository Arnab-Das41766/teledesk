from flask import Flask, send_from_directory, render_template_string

app = Flask(__name__, static_folder='.')

@app.route("/")
def index():
    with open("index.html") as f:
        return render_template_string(f.read())

@app.route("/download")
def download():
    return send_from_directory(".", "setup.exe", as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
