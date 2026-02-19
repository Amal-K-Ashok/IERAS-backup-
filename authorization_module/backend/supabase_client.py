from supabase import create_client
import os

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")


from dotenv import load_dotenv
load_dotenv()  # This loads variables from .env into os.environ


from supabase import create_client, Client
import os
from datetime import datetime

class SupabaseClient:
    def __init__(self):
        # Replace these with your actual Supabase credentials
        self.url = SUPABASE_URL
        self.key = SUPABASE_KEY

        print("SUPABASE_URL =", self.url)
        print("SUPABASE_KEY =", self.key[:4] + "...") 


        self.client: Client = create_client(self.url, self.key)
    
    def authenticate_user(self, username: str, password: str):
        """Authenticate user against authorizers table"""
        try:
            response = self.client.table('authorizers').select('*').eq('username', username).eq('password', password).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Authentication error: {e}")
            return None
    
    def get_all_accidents(self, status_filter=None):
        """Fetch all accidents, optionally filtered by status"""
        try:
            query = self.client.table('accidents').select('*').order('timestamp', desc=True)
            if status_filter:
                query = query.eq('status', status_filter)
            response = query.execute()
            return response.data
        except Exception as e:
            print(f"Error fetching accidents: {e}")
            return []
        

    def get_uploaded_accidents(self):
        """
        Uploaded accidents:
        - status = pending
        - video_url OR clip_path is not null
        """
        try:
            response = (
                self.client
                .table('accidents')
                .select('*')
                .eq('status', 'pending')
                .or_('video_url.not.is.null,clip_path.not.is.null')
                .order('timestamp', desc=True)
                .execute()
            )
            return response.data
        except Exception as e:
            print(f"Error fetching uploaded accidents: {e}")
            return []


    
    def get_accident_by_id(self, accident_id: str):
        """Fetch a specific accident by ID"""
        try:
            response = self.client.table('accidents').select('*').eq('id', accident_id).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            print(f"Error fetching accident: {e}")
            return None
    
    def update_accident_status(self, accident_id: str, status: str, authorized_by: str):
        """Update accident status (approve/reject) with authorizer info"""
        try:
            response = self.client.table('accidents').update({
                'status': status,
                'authorized_by': authorized_by
            }).eq('id', accident_id).execute()
            return response.data
        except Exception as e:
            print(f"Error updating accident status: {e}")
            return None
    
    def get_video_url(self, accident_id: str):
        """Get video URL for a specific accident"""
        try:
            accident = self.get_accident_by_id(accident_id)
            if accident:
                return accident.get('video_url') or accident.get('clip_path')
            return None
        except Exception as e:
            print(f"Error fetching video URL: {e}")
            return None
