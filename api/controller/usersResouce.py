from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError
from model.user import User
from database import db
from flask_restful import abort
import util.status as status

users = Blueprint("users", __name__)

@users.route("/api/user", methods=["POST"])
def user_add():
    """Adds a user in the table.
    """
    if request.content_type == "application/json":
        json = request.get_json()
        if json  == None:
            abort(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, message=f"JSON not valid!")
        new_user = User.from_json(json)
    else:
        abort(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, message=f"Not a JSON!")

    if new_user == None:
        abort(status.HTTP_400_BAD_REQUEST, message=f"Missing data!")

    try:
        db.session.add(new_user)
        db.session.commit()

    except IntegrityError:
        abort(status.HTTP_400_BAD_REQUEST, message=f"User {new_user.username} already exists")
    
    return new_user.to_json(), status.HTTP_201_CREATED
        

@users.route("/api/user", methods=["GET"])
def all_users():
    """Returns all the users that satisfy a pattern (optional),
       form start (default 0) to end (default 100).
    """
    pattern = request.args.get("pattern", default="")

    all_users = User.query.filter(User.username.contains(pattern)).all()

    end = request.args.get("end", default=100, type=int)
    start = request.args.get("start", default=0, type=int)
    all_users = all_users[start:(start + end)]

    json_data = list(map(User.to_json, all_users))
    return jsonify(json_data)

@users.route("/api/user/<string:uname>", methods=["GET"])
def get_user(uname: str):
    """Returns the user with a given id.
    """
    user = User.query.filter(User.username == uname).first()

    if user is None:
        abort(status.HTTP_404_NOT_FOUND, message=f"User {id} does not exists")
        
    return jsonify(user.to_json())  

@users.route("/api/user/<string:uname>", methods=["DELETE"])
def delete_user(uname: str):

    user = User.query.filter(User.username == uname).first()
    if user == None:
        abort(status.HTTP_404_NOT_FOUND, message=f"User {id} does not exists")
    
    db.session.delete(user)
    db.session.commit()

    return "", status.HTTP_204_NO_CONTENT

@users.route("/api/user/<string:uname>", methods=["PUT"])
def update_user(uname: str):
    user = User.query.filter(User.username == uname).first()
    if user == None:
        abort(status.HTTP_404_NOT_FOUND, message=f"User {id} does not exists")
    
    if request.content_type == "application/json":
        user.update_json(request.get_json())
    else:
        abort(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, message=f"Not a JSON or XML!")
    
    db.session.commit()

    return "", status.HTTP_200_OK