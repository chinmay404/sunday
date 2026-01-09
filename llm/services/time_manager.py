import os
import json
import datetime
from datetime import timedelta
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from todoist_api_python.api import TodoistAPI
from dotenv import load_dotenv

# If modifying these scopes, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/calendar']

class TimeManager:
    def __init__(self):
        load_dotenv()
        self.creds = None
        self.service = None
        self.todoist = None
        
        # Paths
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.google_path = os.path.join(os.path.dirname(self.base_path), "graph", "tools", "google")
        self.credentials_path = os.path.join(self.google_path, "google_auth.json")
        self.token_path = os.path.join(self.google_path, "token.json")
        
        # Initialize connections
        self._authenticate_google()
        self._authenticate_todoist()

    def _authenticate_google(self):
        """Authenticates with Google Calendar API."""
        try:
            if os.path.exists(self.token_path):
                self.creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            
            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    self.creds.refresh(Request())
                else:
                    if os.path.exists(self.credentials_path):
                        flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                        self.creds = flow.run_local_server(port=0)
                        with open(self.token_path, 'w') as token:
                            token.write(self.creds.to_json())
                    else:
                        print(f"⚠️ Warning: '{self.credentials_path}' not found. Google Calendar disabled.")
                        return

            self.service = build('calendar', 'v3', credentials=self.creds)
        except Exception as e:
            print(f"⚠️ Google Auth Error: {e}")

    def _authenticate_todoist(self):
        """Authenticates with Todoist API."""
        api_key = os.getenv("TODOIST_API_KEY")
        if api_key:
            self.todoist = TodoistAPI(api_key)
        else:
            print("⚠️ Warning: 'TODOIST_API_KEY' not found. Todoist disabled.")

    def get_time_context(self) -> str:
        """Returns real-time context: Now, Calendar Events, Todoist Tasks."""
        now = datetime.datetime.now().astimezone()
        
        context = {
            "now": now.isoformat(),
            "timezone": str(now.tzinfo),
            "calendar_events": [],
            "pending_tasks": []
        }

        # 1. Fetch Google Calendar Events (Next 48h)
        if self.service:
            try:
                time_min = now.isoformat()
                time_max = (now + timedelta(hours=48)).isoformat()
                
                events_result = self.service.events().list(
                    calendarId='primary', timeMin=time_min, timeMax=time_max,
                    maxResults=10, singleEvents=True, orderBy='startTime'
                ).execute()
                events = events_result.get('items', [])

                for event in events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    context["calendar_events"].append({
                        "summary": event.get('summary', 'No Title'),
                        "start": start,
                        "link": event.get('htmlLink')
                    })
            except Exception as e:
                print(f"Error fetching calendar: {e}")

        # 2. Fetch Todoist Tasks
        if self.todoist:
            try:
                tasks = self.todoist.get_tasks()
                normalized = []
                for task in tasks:
                    try:
                        content = getattr(task, "content", None) or "Unknown task"
                        due_obj = getattr(task, "due", None)
                        due_date = getattr(due_obj, "date", None) if due_obj else None
                        priority = getattr(task, "priority", None)

                        normalized.append((content, due_date, priority))
                    except Exception as inner_err:
                        print(f"Skipping todo item due to parsing error: {inner_err}")
                        continue

                # Sort by due date, keep undated tasks last
                normalized.sort(key=lambda t: t[1] if t[1] else "9999-12-31")

                for content, due_date, priority in normalized[:5]:  # Top 5 regardless of filters
                    context["pending_tasks"].append({
                        "content": content,
                        "due": due_date if due_date else "No date",
                        "priority": priority
                    })
            except Exception as e:
                print(f"Error fetching todos: {e}")

        return json.dumps(context, indent=2)

    # --- Tools Implementation ---

    def add_event(self, summary: str, start_time: str, end_time: str, description: str = ""):
        if not self.service: return "Google Calendar not connected."
        try:
            event = {
                'summary': summary,
                'description': description,
                'start': {'dateTime': start_time, 'timeZone': 'UTC'}, # Adjust TZ as needed
                'end': {'dateTime': end_time, 'timeZone': 'UTC'},
            }
            event = self.service.events().insert(calendarId='primary', body=event).execute()
            return f"Event created: {event.get('htmlLink')}"
        except Exception as e:
            return f"Failed to create event: {e}"

    def add_task(self, content: str, due_string: str = "today"):
        if not self.todoist: return "Todoist not connected."
        try:
            task = self.todoist.add_task(content=content, due_string=due_string)
            return f"Task created: {task.content}"
        except Exception as e:
            return f"Failed to create task: {e}"
