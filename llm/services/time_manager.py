import os
import json
import logging
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

logger = logging.getLogger(__name__)

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

    def _run_google_oauth_flow(self, flow: InstalledAppFlow):
        """Run OAuth flow with optional headless/console mode."""
        flow_mode = os.getenv("GOOGLE_OAUTH_FLOW", "local").strip().lower()
        headless = os.getenv("GOOGLE_OAUTH_HEADLESS", "").strip().lower() in {"1", "true", "yes", "on"}

        use_console = headless or flow_mode in {"console", "headless"}
        if use_console:
            redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
            if not redirect_uri:
                # Default to OOB for manual code copy. Can be overridden via env var.
                redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
            flow.redirect_uri = redirect_uri
            if hasattr(flow, "run_console"):
                return flow.run_console()
            auth_url, _ = flow.authorization_url(prompt="consent")
            print("Open this URL to authorize Google Calendar access:")
            print(auth_url)
            code = input("Enter the authorization code: ").strip()
            flow.fetch_token(code=code)
            return flow.credentials

        # Default: local server flow (opens browser)
        return flow.run_local_server(port=0)

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
                        self.creds = self._run_google_oauth_flow(flow)
                        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
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
                    })
            except Exception as e:
                logger.error("Error fetching calendar: %s", e)

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
                        logger.warning("Skipping todo item due to parsing error: %s", inner_err)
                        continue

                # Sort by due date, keep undated tasks last
                normalized.sort(key=lambda t: t[1] if t[1] else "9999-12-31")

                for content, due_date, priority in normalized[:5]:  # Top 5 regardless of filters
                    # Skip useless placeholder tasks
                    if not content or content.strip().lower() in ("unknown task", ""):
                        continue
                    context["pending_tasks"].append({
                        "content": content,
                        "due": due_date if due_date else "No date",
                        "priority": priority
                    })
            except Exception as e:
                logger.error("Error fetching todos: %s", e)

        # Drop empty sections to save tokens
        if not context["pending_tasks"]:
            del context["pending_tasks"]
        if not context["calendar_events"]:
            del context["calendar_events"]

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

    def list_events(self, days_ahead: int = 2):
        """List upcoming calendar events for the next N days."""
        if not self.service:
            return "Google Calendar not connected."
        try:
            now = datetime.datetime.now().astimezone()
            time_min = now.isoformat()
            time_max = (now + timedelta(days=days_ahead)).isoformat()
            events_result = self.service.events().list(
                calendarId='primary', timeMin=time_min, timeMax=time_max,
                maxResults=20, singleEvents=True, orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])
            if not events:
                return f"No events in the next {days_ahead} day(s)."
            lines = []
            for ev in events:
                start = ev['start'].get('dateTime', ev['start'].get('date'))
                end = ev['end'].get('dateTime', ev['end'].get('date', ''))
                summary = ev.get('summary', 'No Title')
                event_id = ev.get('id', '')
                lines.append(f"• {summary} | {start} → {end} | ID: {event_id}")
            return "\n".join(lines)
        except Exception as e:
            return f"Failed to list events: {e}"

    def delete_event(self, event_id: str):
        """Delete a calendar event by ID."""
        if not self.service:
            return "Google Calendar not connected."
        try:
            self.service.events().delete(calendarId='primary', eventId=event_id).execute()
            return f"Event {event_id} deleted."
        except Exception as e:
            return f"Failed to delete event: {e}"

    def list_tasks(self, filter_str: str = "today | overdue"):
        """List Todoist tasks with optional filter."""
        if not self.todoist:
            return "Todoist not connected."
        try:
            tasks = self.todoist.get_tasks(filter=filter_str)
            if not tasks:
                return "No tasks matching that filter."
            lines = []
            for task in tasks:
                content = getattr(task, "content", "Unknown")
                task_id = getattr(task, "id", "")
                due_obj = getattr(task, "due", None)
                due_str = getattr(due_obj, "date", "No date") if due_obj else "No date"
                priority = getattr(task, "priority", 1)
                p_label = {4: "🔴", 3: "🟠", 2: "🟡"}.get(priority, "")
                lines.append(f"• {p_label}{content} | due: {due_str} | ID: {task_id}")
            return "\n".join(lines)
        except Exception as e:
            return f"Failed to list tasks: {e}"

    def complete_task(self, task_id: str):
        """Complete a Todoist task by ID."""
        if not self.todoist:
            return "Todoist not connected."
        try:
            self.todoist.close_task(task_id=task_id)
            return f"Task {task_id} completed ✓"
        except Exception as e:
            return f"Failed to complete task: {e}"
