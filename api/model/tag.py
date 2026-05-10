from database import db
from flask_restful import abort
import util.status as status

class Tag(db.Model):

    # Table name and columns
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(250), unique=True, nullable=False)

    def __init__(self, name : str) -> None:
        """Adds a tag in the table.
        """
        self.name = name


    def to_json(self) -> dict:
        """From tag to JSON.
        """
        resource = {
            "id": self.id,
            "name" : self.name
        }
        return resource
    
    @staticmethod
    def from_json(data: dict) -> None:
        """From JSON to tag.

        Args: 
            data: input JSON.
        """
        try:
            
            return Tag.query.filter(Tag.name == data.get("name")).first()

        except KeyError:
            abort(status.HTTP_404_NOT_FOUND, message=f"Tag does not exist")

        except IndexError:
            abort(status.HTTP_404_NOT_FOUND, message=f"Tag does not exist")