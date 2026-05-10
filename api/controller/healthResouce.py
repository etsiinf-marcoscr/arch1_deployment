from flask import Blueprint
import util.status as status

health = Blueprint("health", __name__)

@health.route("/api/health", methods=["GET"])
def healthcheck():
    return "OK", status.HTTP_200_OK