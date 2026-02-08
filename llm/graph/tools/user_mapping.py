from langchain_core.tools import tool
# from llm.services.time_manager import TimeManager
# from llm.graph.tools.reminders.weakup_tools import _create_reminder
import json
from typing import Any, Dict, List, Optional

@tool
def add_user_in_known_user(user_id : str , user_name : str , description : Optional[str], **kwargs):
    """
    add a person in known User list 
    """
    try:
        users = json.load(open("llm/graph/nodes/user_map.json"))
        if user_id in users:
            user = users[user_id]
            return f"User Already Known as  {user}"
        else: 
            users[user_id] = {"user_name" : user_name , "description" : description , "Additional" : str(**kwargs)  }
            with open("llm/graph/nodes/user_map.json" , "w") as f:
                json.dump(users , f)
            return f"User {user_name} added successfully"
    except Exception as e: 
        print(f"error in writing file : {e}")
        return "Error in adding user"
    


@tool
def map_user(user_id : str) :
    """will Map user and return who is this actually"""
    try:
        users = json.load(open("llm/graph/nodes/user_map.json"))
        if user_id in users:
            user = users[user_id]
            return user
        else:
            return "User Not in List Ask for Further Information"
    except Exception as e:
        print(f"Erorr in Mapping User : {e}")
        return "Error in mapping user"



@tool
def add_thing_to_remeber(user_id : str , thing : str) :
    """will add thing to remember for user"""
    try:
        users = json.load(open("llm/graph/nodes/user_map.json"))
        if user_id in users:
            user = users[user_id]
            if "remember" not in user:
                user["remember"] = []
            user["remember"].append(thing)
            with open("llm/graph/nodes/user_map.json" , "w") as f:
                json.dump(users , f)
            return f"Thing added to remember for user {user_id}"
        else:
            return "User Not in List Ask for Further Information"
    except Exception as e:
        print(f"Erorr in Adding Thing to Remember : {e}")
        return "Error in adding thing to remember"