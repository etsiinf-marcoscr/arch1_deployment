from database import db
from model.user import User
from model.game import Game

games = db.Table('games_rel',
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True),
    db.Column('orders_id', db.Integer, db.ForeignKey('orders.id'), primary_key=True)
)

class Order(db.Model):

    # Table name and columns
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    games = db.relationship('Game', secondary=games, lazy='subquery',
        backref=db.backref('games', lazy=True))
    user_id =  db.Column(db.Integer, db.ForeignKey('users.id'))
    user = db.relationship("User")
    address = db.Column(db.String(1000), unique=False, nullable=False)
    status = db.Column(db.String(250), unique=False, nullable=False)

    def __init__(self, games : list, user : User, address : str, status : str) -> None:
        """Adds a order in the table.
        """
        self.games = games
        self.user = user
        self.address = address
        self.status = status

    def to_json(self) -> dict:
        """From order to JSON.
        """
        games_serialized = [game.to_json() for game in self.games]

        resource = {
            "id": self.id,
            "games" : games_serialized,
            "user" : self.user.to_json(),
            "address" : self.address,
            "status" : self.status
        }
        return resource
    
    @staticmethod
    def from_json(data: dict) -> None:
        """From JSON to order.

        Args: 
            data: input JSON.
        """
        try:
            my_games = data.get("games")
            my_games_deserialized = [Game.from_json_id(my_game) for my_game in my_games]
            my_user = User.from_json_username(data.get("user"))
            my_address = data.get("address")
            my_status = data.get("status")

            return Order(my_games_deserialized, my_user, my_address, my_status)

        except KeyError:
            return None

        except IndexError:
            return None

    def update_order(self, data: dict) -> None:
        """Update a order from JSON.

        Args: 
            data: input JSON.
        """
        try:
            self.status = data.get("status")
            self.address = data.get("address")

        except:
            pass
