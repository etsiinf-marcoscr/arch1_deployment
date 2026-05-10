from database import db
from model.category import Category
from model.tag import Tag
from werkzeug.exceptions import NotFound

tags = db.Table('tags_rel',
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True),
    db.Column('game_id', db.Integer, db.ForeignKey('games.id'), primary_key=True)
)

class Game(db.Model):

    # Table name and columns
    __tablename__ = 'games'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(250), unique=False, nullable=False)
    available_quantity = db.Column(db.Integer, unique=False, nullable=False)
    category_id =  db.Column(db.Integer, db.ForeignKey('categories.id'))
    category = db.relationship("Category")
    photo_url = db.Column(db.String(1000), unique=False, nullable=False)
    tags = db.relationship('Tag', secondary=tags, lazy='subquery',
        backref=db.backref('games', lazy=True))

    def __init__(self, name : str, available_quantity : int, category : Category, photo_url : str, tags : list) -> None:
        """Adds a game in the table.
        """
        self.name = name
        self.available_quantity = available_quantity
        self.category = category
        self.photo_url = photo_url
        self.tags = tags


    def to_json(self) -> dict:
        """From game to JSON.
        """
        tags_serialized = [tag.to_json() for tag in self.tags]

        resource = {
            "id": self.id,
            "name" : self.name,
            "availableQuantity" : self.available_quantity,
            "category" : self.category.to_json(),
            "photoUrl" : self.photo_url,
            "tags" : tags_serialized
        }
        return resource
    
    @staticmethod
    def from_json(data: dict) -> None:
        """From JSON to game.

        Args: 
            data: input JSON.
        """
        try:

            my_name = data.get("name").rstrip()
            my_available_quantity = data.get("availableQuantity")
            my_category = Category.from_json(data.get("category"))
            my_photo_url = data.get("photoUrl").rstrip()
            my_tags = data.get("tags")
            my_tags_deserialized = [Tag.from_json(my_tag) for my_tag in my_tags]

            return Game(my_name, my_available_quantity, my_category, my_photo_url, my_tags_deserialized)

        except KeyError:
            return None

        except IndexError:
            return None
  
    @staticmethod
    def from_json_id(data: dict) -> None:
        """From JSON to game.

        Args: 
            data: input JSON.
        """
        try:
            my_id = data.get("id")
            game = Game.query.filter(Game.id == my_id).first()

            if game is None:
                raise NotFound("Game does not exist")
        
            return game  
        except KeyError:
            return None

        except IndexError:
            return None

    def update_json(self, data: dict) -> None:
        """Update a game from JSON.

        Args: 
            data: input JSON.
        """
        try:

            self.name = data.get("name").rstrip()
            self.available_quantity = data.get("availableQuantity")
            self.category = Category.from_json(data.get("category"))
            self.photo_url = data.get("photoUrl").rstrip()
            my_tags = data.get("tags")
            my_tags_deserialized = [Tag.from_json(my_tag) for my_tag in my_tags]
            self.tags = my_tags_deserialized

        except:
            pass
