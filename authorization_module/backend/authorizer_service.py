from supabase_client import SupabaseClient
from datetime import datetime

class AuthorizerService:
    def __init__(self):
        self.db = SupabaseClient()
    
    def login(self, username: str, password: str):
        """Authenticate and return user data"""
        user = self.db.authenticate_user(username, password)
        if user:
            return {
                'success': True,
                'user': {
                    'id': user['id'],
                    'username': user['username'],
                    'role': user['role']
                }
            }
        return {'success': False, 'message': 'Invalid credentials'}
    
    def get_pending_accidents(self):
        """Get all pending accidents"""
        accidents = self.db.get_all_accidents(status_filter='pending')
        return self._convert_video_urls(accidents)
    
    def get_all_accidents(self):
        """Get all accidents regardless of status"""
        accidents = self.db.get_all_accidents()
        return self._convert_video_urls(accidents)
    
    def get_uploaded_accidents(self):
        accidents = self.db.get_uploaded_accidents()
        return self._convert_video_urls(accidents)
    
    def get_accidents_by_status(self, status: str):
        """
        Supported statuses:
        - pending
        - approved
        - rejected
        - uploaded (special case)
        """
        if status == "uploaded":
            accidents = self.db.get_uploaded_accidents()
        else:
            accidents = self.db.get_all_accidents(status_filter=status)
        
        return self._convert_video_urls(accidents)
    
    def approve_accident(self, accident_id: str, authorizer_username: str):
        """Approve an accident report"""
        result = self.db.update_accident_status(accident_id, 'approved', authorizer_username)
        if result:
            return {'success': True, 'message': 'Accident approved successfully'}
        return {'success': False, 'message': 'Failed to approve accident'}
    
    def reject_accident(self, accident_id: str, authorizer_username: str):
        """Reject an accident report"""
        result = self.db.update_accident_status(accident_id, 'rejected', authorizer_username)
        if result:
            return {'success': True, 'message': 'Accident rejected successfully'}
        return {'success': False, 'message': 'Failed to reject accident'}
    
    def get_accident_details(self, accident_id: str):
        """Get detailed information about a specific accident"""
        accident = self.db.get_accident_by_id(accident_id)
        if accident:
            return self._convert_single_video_url(accident)
        return None
    
    def get_video_url(self, accident_id: str):
        """Get video URL for playback (proxied)"""
        video_url = self.db.get_video_url(accident_id)
        if video_url and 'supabase.co/storage/v1/object/public/videos/' in video_url:
            # Extract filename and convert to proxy URL
            filename = video_url.split('/videos/')[-1]
            return f'/api/video-proxy/{filename}'
        return video_url
    
    def _convert_single_video_url(self, accident):
        """Convert Supabase storage URL to proxy URL for a single accident"""
        if accident and accident.get('video_url'):
            video_url = accident['video_url']
            
            # Check if it's a Supabase storage URL
            if 'supabase.co/storage/v1/object/public/videos/' in video_url:
                # Extract the filename from the URL
                filename = video_url.split('/videos/')[-1]
                # Replace with proxy URL
                accident['video_url'] = f'/api/video-proxy/{filename}'
        
        return accident
    
    def _convert_video_urls(self, accidents):
        """Convert Supabase storage URLs to proxy URLs for a list of accidents"""
        if not accidents:
            return []
        
        for accident in accidents:
            self._convert_single_video_url(accident)
        
        return accidents