# mock_imds/app.py
from flask import Flask, request, jsonify
import datetime, os
from azure.storage.blob import BlobServiceClient

app = Flask(__name__)

FORensics_CONNSTR = os.environ.get("FORENSICS_CONNSTR")  # connection string for a forensics container
FOR_CONTAINER = os.environ.get("FORENSICS_CONTAINER", "forensics-logs")

def save_log(payload):
    if not FORensics_CONNSTR:
        print("[forensics]", payload)
        return
    client = BlobServiceClient.from_connection_string(FORensics_CONNSTR)
    cont = client.get_container_client(FOR_CONTAINER)
    try:
        cont.create_container()
    except Exception:
        pass
    name = "imds-log-" + datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ") + ".json"
    cont.get_blob_client(name).upload_blob(payload.encode('utf-8'), overwrite=True)

@app.route("/metadata/identity/oauth2/token", methods=["GET","POST"])
def token():
    # IMDS-like query: ?resource=https://management.azure.com&api-version=2017-09-01
    # Accept if Metadata:true or secret header matches.
    metadata = request.headers.get("Metadata", "")
    secret = request.headers.get("secret", "")
    ua = request.headers.get("User-Agent", "")
    remote = request.remote_addr

    entry = {
        "time": datetime.datetime.utcnow().isoformat(),
        "remote_addr": remote,
        "headers": dict(request.headers),
        "args": request.args.to_dict()
    }
    save_log(jsonify(entry).get_data(as_text=True))

    # reward the request (simulate MI token) if header present or Metadata true
    if metadata.lower() == "true" or secret == os.environ.get("BACKUP_IDENTITY_HEADER","BACKUP-SECRET"):
        token = {
            "access_token": "FAKE_MI_TOKEN_{}".format(datetime.datetime.utcnow().strftime("%s")),
            "expires_in": 3599,
            "token_type": "Bearer"
        }
        return jsonify(token)
    else:
        return jsonify({"error":"Unauthorized - missing Metadata or secret header"}), 401

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
