from configparser import ConfigParser
from dotenv import load_dotenv
import os
from pathlib import Path


load_dotenv()
db_password = os.getenv('db_password')
#base_dir = Path(__file__).resolve().parent

current_dir = Path(__file__).parent.resolve()
DB_FILENAME = current_dir/'database.ini'



def config(filename: str = DB_FILENAME, section: str = 'postgresql', check: str = db_password) -> dict:
    """Read database configuration from a file and return a dictionary.

    Args:
        filename (str): The name of the configuration file.
        section (str): The section of the configuration file to read.

    Returns:
        dict: A dictionary containing the database configuration.
    """
    parser = ConfigParser()
    found= parser.read(filename)


    # Debug check: verify the file was actually found
    if not found:
        raise FileNotFoundError(f"Could not find database.ini at: {filename}")
    

    if not parser.has_section(section):
        raise Exception(f"Section {section} not found in the 'database.ini' file")

    db = {}
    params = parser.items(section)
    for param in params:
        db[param[0]] = param[1]

    db['password'] = check

    return db

if __name__ == "__main__":
    config()