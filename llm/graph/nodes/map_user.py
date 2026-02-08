import json

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
    