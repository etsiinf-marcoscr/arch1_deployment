from flask import Flask
from flask_cors import CORS
from controller.usersResouce import users
from controller.categoryResource import categories
from controller.tagResource import tags
from controller.gameResource import games
from controller.orderResource import orders
from controller.healthResouce import health
import os

db_user = 'aws'
db_password = 'flaskroot'

DATABASE_URI = os.environ.get('DATABASE_URI', f"postgresql://{db_user}:{db_password}@localhost/practica")

def create_api():
    api = Flask(__name__)
    api.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URI
    api.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    cors = CORS(api)

    api.register_blueprint(users)
    api.register_blueprint(games)
    api.register_blueprint(orders)
    api.register_blueprint(categories)
    api.register_blueprint(tags)
    api.register_blueprint(health)

    return api

