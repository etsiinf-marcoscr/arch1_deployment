from flask import Blueprint, jsonify, request
from model.tag import Tag
from flask_restful import abort
import util.status as status

tags = Blueprint("tags", __name__)

@tags.route("/api/tag", methods=["GET"])
def all_tags():
    """Returns all the tags that satisfy a pattern (optional),
       form start (default 0) to end (default 100).
    """
    pattern = request.args.get("pattern", default="")

    all_tags = Tag.query.filter(Tag.name.contains(pattern)).all()

    end = request.args.get("end", default=100, type=int)
    start = request.args.get("start", default=0, type=int)
    all_tags = all_tags[start:(start + end)]

    json_data = list(map(Tag.to_json, all_tags))
    return jsonify(json_data)

@tags.route("/api/tag/<int:id>", methods=["GET"])
def get_category(id: int):
    """Returns the tag with a given id.
    """

    tag = Tag.query.filter(Tag.id == id).first()

    if tag is None:
        abort(status.HTTP_404_NOT_FOUND, message=f"Tag {id} does not exists")
        
    return jsonify(tag.to_json())  