from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError
from model.game import Game
from database import db
from flask_restful import abort
import util.status as status
from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import NotFound
from werkzeug.exceptions import UnsupportedMediaType

games = Blueprint("games", __name__)

@games.route("/api/game", methods=["POST"])
def game_add():
    """Adds a game in the table given a JSON as request.
    """
    if request.content_type == "application/json":
        json = request.get_json()
        if json  == None:
            raise UnsupportedMediaType("JSON not valid")
        new_game = Game.from_json(json)
    else:
        raise UnsupportedMediaType("Not a JSON")

    if new_game == None:
        raise BadRequest("Missing data!")

    try:
        db.session.add(new_game)
        db.session.commit()

    except IntegrityError:
        raise BadRequest(f"Game {new_game.name} already exists")
    
    return games.to_json(), status.HTTP_201_CREATED
        

@games.route("/api/game", methods=["GET"])
def all_games():
    """Returns all the games that satisfy a pattern (optional),
       form start (default 0) to end (default 100).
    """
    pattern = request.args.get("pattern", default="")

    all_games = Game.query.filter(Game.name.contains(pattern)).all()

    end = request.args.get("end", default=100, type=int)
    start = request.args.get("start", default=0, type=int)
    all_games = all_games[start:(start + end)]

    json_data = list(map(Game.to_json, all_games))
    return jsonify(json_data)

@games.route("/api/game/<int:id>", methods=["GET"])
def get_game(id: int):
    """Returns the game with a given id.
    """

    game = Game.query.filter(Game.id == id).first()

    if game is None:
        raise NotFound(f"Game {id} doesn't exists")
        
    return jsonify(game.to_json())  

@games.route("/api/game/<int:id>", methods=["DELETE"])
def delete_game(id: int):

    game = Game.query.filter(Game.id == id).first()
    if game == None:
        abort(status.HTTP_404_NOT_FOUND, message=f"Game {id} does not exists")
    
    db.session.delete(game)
    db.session.commit()

    return "", status.HTTP_204_NO_CONTENT

@games.route("/api/game/<int:id>", methods=["PUT"])
def update_game(id: int):
    game = Game.query.filter(Game.id == id).first()
    if game == None:
        abort(status.HTTP_404_NOT_FOUND, message=f"Game {id} does not exists")
    
    if request.content_type == "application/json":
        game.update_json(request.get_json())
    else:
        abort(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, message=f"Not a JSON or XML!")
    
    db.session.commit()

    return "", status.HTTP_200_OK