from database import db
from werkzeug.exceptions import NotFound

class Category(db.Model):

    # Table name and columns
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(250), unique=True, nullable=False)

    def __init__(self, name : str) -> None:
        """Adds a category in the table.
        """

        self.name = name


    def to_json(self) -> dict:
        """From category to JSON.
        """
        resource = {
            "id": self.id,
            "name" : self.name
        }
        return resource
    
    @staticmethod
    def from_json(data: dict) -> None:
        """From JSON to category.

        Args: 
            data: input JSON.
        """
        try:
            cat = Category.query.filter(Category.name == data.get("name")).first()
            if cat == None:
                raise NotFound("Category does not exist")
            return cat
        except KeyError:
            raise NotFound("Category does not exist")

        except IndexError:
            raise NotFound("Category does not exist")

    