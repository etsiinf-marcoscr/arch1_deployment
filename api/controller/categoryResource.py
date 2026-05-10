from flask import Blueprint, jsonify, request
from model.category import Category
from flask_restful import abort
import util.status as status

categories = Blueprint("categories", __name__)

@categories.route("/api/category", methods=["GET"])
def all_categories():
    """Returns all the categories that satisfy a pattern (optional),
       form start (default 0) to end (default 100).
    """
    
    pattern = request.args.get("pattern", default="")

    all_categories = Category.query.filter(Category.name.contains(pattern)).all()

    end = request.args.get("end", default=100, type=int)
    start = request.args.get("start", default=0, type=int)
    all_categories = all_categories[start:(start + end)]

    json_data = list(map(Category.to_json, all_categories))
    return jsonify(json_data)

@categories.route("/api/category/<int:id>", methods=["GET"])
def get_category(id: int):
    """Returns the category with a given id.
    """

    category = Category.query.filter(Category.id == id).first()

    if category is None:
        abort(status.HTTP_404_NOT_FOUND, message=f"Category {id} does not exists")
        
    return jsonify(category.to_json())  