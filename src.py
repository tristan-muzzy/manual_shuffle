import json
import math
import time
import base64
import random
import requests
import webbrowser
import urllib.parse as urlparse
from datetime import datetime
from typing import Dict, List, Set, Optional, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode


class Song:
    """Represents a single track with user ratings and metadata"""

    def __init__(self, track_data_from_spotify: Dict[str, Any], audio_features_to_pull: Optional[List[str]] = None):
        # Basic metadata from Spotify
        self.name = track_data_from_spotify['name']
        self.artist = track_data_from_spotify['artists'][0]['name']  # Primary artist
        self.album = track_data_from_spotify['album']['name']
        self.spotify_id = track_data_from_spotify['id']

        # User attributes
        self.stars = 5  # Default rating 1-10

        # Genres from artist data (populated later)
        self.genres = set()

        # Audio features - only track what we need
        default_features = {'instrumentalness': None}
        self.audio_features = default_features.copy()

        if audio_features_to_pull:
            for feature in audio_features_to_pull:
                if feature not in self.audio_features:
                    self.audio_features[feature] = None

        # Timestamps as datetime objects internally
        self.date_added = datetime.now()
        self.last_updated = datetime.now()

    def update_from_spotify(self, track_data: Dict[str, Any], preserve_user_data: bool = True):
        """Update metadata from fresh Spotify data, optionally preserving user modifications"""
        if not preserve_user_data:
            self.stars = 5  # Reset to default

        # Always update metadata in case Spotify data changed
        self.name = track_data['name']
        self.artist = track_data['artists'][0]['name']
        self.album = track_data['album']['name']
        self.last_updated = datetime.now()

    def update_audio_features(self, features_dict: Dict[str, float]):
        """Update audio features from Spotify API response"""
        for feature, value in features_dict.items():
            if feature in self.audio_features:
                self.audio_features[feature] = value
        self.last_updated = datetime.now()

    def add_genres(self, genres: List[str]):
        """Add genres from artist data"""
        self.genres.update(genres)
        self.last_updated = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary"""
        return {
            'name': self.name,
            'artist': self.artist,
            'album': self.album,
            'stars': self.stars,
            'genres': list(self.genres),  # Convert set to list for JSON
            'audio_features': self.audio_features,
            'date_added': self.date_added.strftime('%d/%m/%Y'),
            'last_updated': self.last_updated.strftime('%d/%m/%Y')
        }

    @classmethod
    def from_dict(cls, spotify_id: str, data_dict: Dict[str, Any]) -> 'Song':
        """Reconstruct Song object from JSON dictionary"""
        # Create minimal track data for __init__
        fake_track_data = {
            'name': data_dict['name'],
            'artists': [{'name': data_dict['artist']}],
            'album': {'name': data_dict['album']},
            'id': spotify_id
        }

        # Create song object
        song = cls(fake_track_data, list(data_dict['audio_features'].keys()))

        # Restore saved data
        song.stars = data_dict['stars']
        song.genres = set(data_dict['genres'])
        song.audio_features = data_dict['audio_features']
        song.date_added = datetime.strptime(data_dict['date_added'], '%d/%m/%Y')
        song.last_updated = datetime.strptime(data_dict['last_updated'], '%d/%m/%Y')

        return song


class PlaylistManager(dict):
    """Dictionary of Song objects keyed by Spotify ID with JSON persistence"""

    def __init__(self, json_file: Optional[str] = None, audio_features_to_track: Optional[List[str]] = None):
        super().__init__()
        self.audio_features_to_track = audio_features_to_track or ['instrumentalness']
        self.json_file = json_file

        if json_file:
            self.load_from_json(json_file)

    def add_song(self, track_data_from_spotify: Dict[str, Any]) -> Song:
        """Add new song or update existing one, preserving user data"""
        spotify_id = track_data_from_spotify['id']

        if spotify_id in self:
            # Update existing song
            self[spotify_id].update_from_spotify(track_data_from_spotify, preserve_user_data=True)
        else:
            # Create new song
            song = Song(track_data_from_spotify, self.audio_features_to_track)
            self[spotify_id] = song

        return self[spotify_id]

    def get_name_to_id_map(self) -> Dict[str, str]:
        """Returns dictionary mapping 'Song Name - Artist' to Spotify ID"""
        return {f"{song.name} - {song.artist}": spotify_id
                for spotify_id, song in self.items()}

    def save_to_json(self, filename: Optional[str] = None) -> bool:
        """Save all songs to JSON file"""
        file_to_use = filename or self.json_file
        if not file_to_use:
            print("No filename provided for saving")
            return False

        try:
            json_data = {spotify_id: song.to_dict()
                         for spotify_id, song in self.items()}

            with open(file_to_use, 'w') as f:
                json.dump(json_data, f, indent=2)

            return True

        except (IOError, OSError) as e:
            print(f"Error saving to {file_to_use}: {e}")
            return False
        print(f"Saved {len(self)} songs to {file_to_use}")

    def load_from_json(self, filename: str) -> bool:
        """Load songs from JSON file"""
        try:
            with open(filename, 'r') as f:
                json_data = json.load(f)

            # Clear existing data and load from JSON
            self.clear()
            for spotify_id, song_data in json_data.items():
                self[spotify_id] = Song.from_dict(spotify_id, song_data)

            return True

        except FileNotFoundError:
            print(f"File {filename} not found, starting with empty playlist")
            return False
        except (IOError, OSError, json.JSONDecodeError) as e:
            print(f"Error loading from {filename}: {e}")
            return False


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback"""

    def do_GET(self):
        # Parse the callback URL to extract the authorization code
        query_components = dict(urlparse.parse_qsl(urlparse.urlparse(self.path).query))

        if 'code' in query_components:
            self.server.auth_code = query_components['code']
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(
                b'<html><body><h1>Authorization successful!</h1><p>You can close this window.</p></body></html>')
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body><h1>Authorization failed!</h1></body></html>')


class SpotifyPlaylistAPI:
    """Complete Spotify API client with OAuth and playlist management"""

    def __init__(self, client_id: Optional[str] = None, client_secret: Optional[str] = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = "http://127.0.0.1:8000/callback"
        self.access_token = None
        self.refresh_token = None

        # Load credentials if not provided
        if not client_id or not client_secret:
            self._load_credentials()

    def _load_credentials(self):
        """Load Spotify credentials from secret.txt file"""
        try:
            with open('secret.txt', 'r') as f:
                lines = f.read().strip().split('\n')
                for line in lines:
                    if '=' in line:
                        key, value = line.split('=', 1)
                        if key.strip() == 'CLIENT_ID':
                            self.client_id = value.strip()
                        elif key.strip() == 'CLIENT_SECRET':
                            self.client_secret = value.strip()

            if not self.client_id or not self.client_secret:
                print("CLIENT_ID and CLIENT_SECRET must be in secret.txt file")
                print("Format: CLIENT_ID=your_client_id\\nCLIENT_SECRET=your_client_secret")

        except FileNotFoundError:
            print("secret.txt file not found. Create it with:")
            print("CLIENT_ID=your_client_id")
            print("CLIENT_SECRET=your_client_secret")
        except Exception as e:
            print(f"Error loading credentials: {e}")

    def authenticate(self) -> bool:
        """Handle the full OAuth flow"""
        if not self.client_id or not self.client_secret:
            print("Missing Spotify credentials")
            return False

        # Get authorization URL and open in browser
        auth_url = self._get_auth_url()
        print("Opening browser for Spotify authorization...")
        webbrowser.open(auth_url)

        # Start local server to catch callback
        server = HTTPServer(('127.0.0.1', 8000), CallbackHandler)
        server.auth_code = None

        print("Waiting for authorization...")
        server.handle_request()  # Handle one request (the callback)

        if server.auth_code:
            if self._exchange_code_for_token(server.auth_code):
                print("Authentication successful!")
                return True
            else:
                print("Token exchange failed!")
                return False
        else:
            print("Authorization failed!")
            return False

    def _get_auth_url(self) -> str:
        """Generate the authorization URL for user login"""
        auth_params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'scope': 'user-library-read playlist-modify-public playlist-modify-private playlist-read-private user-read-private',
            'show_dialog': 'true'
        }

        return f"https://accounts.spotify.com/authorize?{urlencode(auth_params)}"

    def _exchange_code_for_token(self, auth_code: str) -> bool:
        """Exchange authorization code for access token"""
        try:
            auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

            headers = {
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            data = {
                'grant_type': 'authorization_code',
                'code': auth_code,
                'redirect_uri': self.redirect_uri
            }

            response = requests.post('https://accounts.spotify.com/api/token', headers=headers, data=data)

            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token')
                return True
            else:
                print(f"Error getting token: {response.text}")
                return False

        except Exception as e:
            print(f"Error during token exchange: {e}")
            return False

    def _refresh_access_token(self) -> bool:
        """Refresh the access token using refresh token"""
        if not self.refresh_token:
            return False

        try:
            auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

            headers = {
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            data = {
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token
            }

            response = requests.post('https://accounts.spotify.com/api/token', headers=headers, data=data)

            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                return True

        except Exception as e:
            print(f"Error refreshing token: {e}")

        return False

    def _make_api_request(self, endpoint: str, method: str = 'GET', data: Optional[Dict] = None):
        """Make authenticated API requests with automatic token refresh"""
        if not self.access_token:
            raise Exception("No access token available")

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        url = f'https://api.spotify.com/v1/{endpoint}'

        try:
            if method == 'GET':
                response = requests.get(url, headers=headers)
            elif method == 'POST':
                response = requests.post(url, headers=headers, data=json.dumps(data) if data else None)
            elif method == 'PUT':
                response = requests.put(url, headers=headers, data=json.dumps(data) if data else None)
            elif method == 'DELETE':
                response = requests.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # Handle token expiration
            if response.status_code == 401:
                if self._refresh_access_token():
                    headers['Authorization'] = f'Bearer {self.access_token}'
                    # Retry the request
                    if method == 'GET':
                        response = requests.get(url, headers=headers)
                    elif method == 'POST':
                        response = requests.post(url, headers=headers, data=json.dumps(data) if data else None)
                    elif method == 'PUT':
                        response = requests.put(url, headers=headers, data=json.dumps(data) if data else None)
                    elif method == 'DELETE':
                        response = requests.delete(url, headers=headers)

            return response

        except Exception as e:
            print(f"Error making API request: {e}")
            raise

    def get_user_id(self) -> Optional[str]:
        """Get current user's Spotify ID"""
        try:
            response = self._make_api_request('me')
            if response.status_code == 200:
                return response.json()['id']
        except Exception as e:
            print(f"Error getting user ID: {e}")
        return None

    def create_playlist(self, name: str, description: str = "", public: bool = False) -> Optional[Dict]:
        """Create a new playlist"""
        try:
            user_id = self.get_user_id()
            if not user_id:
                return None

            data = {
                'name': name,
                'description': description,
                'public': public
            }

            response = self._make_api_request(f'users/{user_id}/playlists', method='POST', data=data)

            if response.status_code == 201:
                return response.json()
            else:
                print(f"Playlist creation error: {response.text}")
                return None

        except Exception as e:
            print(f"Error creating playlist: {e}")
            return None

    def add_tracks_to_playlist(self, playlist_id: str, track_uris: List[str]) -> bool:
        """Add tracks to a playlist (track_uris should be list of Spotify URIs)"""
        try:
            # Spotify allows max 100 tracks per request
            chunk_size = 100

            for i in range(0, len(track_uris), chunk_size):
                chunk = track_uris[i:i + chunk_size]
                data = {'uris': chunk}

                response = self._make_api_request(f'playlists/{playlist_id}/tracks', method='POST', data=data)

                if response.status_code != 201:
                    print(f"Error adding tracks: {response.text}")
                    return False

            return True

        except Exception as e:
            print(f"Error adding tracks to playlist: {e}")
            return False

    def get_track_features(self, track_ids: List[str]) -> List[Dict]:
        """Get audio features for tracks (for algorithm purposes)"""
        try:
            # Spotify allows max 100 track IDs per request
            chunk_size = 100
            all_features = []

            for i in range(0, len(track_ids), chunk_size):
                chunk = track_ids[i:i + chunk_size]
                ids_str = ','.join(chunk)

                response = self._make_api_request(f'audio-features?ids={ids_str}')

                if response.status_code == 200:
                    features = response.json()['audio_features']
                    all_features.extend([f for f in features if f is not None])
                elif response.status_code == 403:
                    print("403 error accessing audio features - this may require Spotify Premium")
                    print("Continuing without audio features...")
                    break
                else:
                    print(f"Error getting features (status {response.status_code}): {response.text}")
                    break

            return all_features

        except Exception as e:
            print(f"Error fetching audio features: {e}")
            return []

    def get_liked_songs(self, audio_features_to_pull: Optional[List[str]] = None) -> PlaylistManager:
        """Retrieve all liked songs and return as PlaylistManager"""
        playlist_manager = PlaylistManager(audio_features_to_track=audio_features_to_pull)

        try:
            # Debug: Check if we can access user profile first
            user_response = self._make_api_request('me')
            if user_response.status_code != 200:
                print(f"Cannot access user profile: {user_response.status_code} - {user_response.text}")
                return playlist_manager

            print(f"Authenticated as: {user_response.json().get('display_name')}")

            # Get liked songs (Spotify's 'saved tracks')
            offset = 0
            limit = 50
            total_tracks = 0

            while True:
                print(f"Fetching tracks {offset}-{offset + limit}...")
                response = self._make_api_request(f'me/tracks?limit={limit}&offset={offset}')

                if response.status_code != 200:
                    print(f"Error fetching liked songs at offset {offset}: {response.status_code}")
                    print(f"Response: {response.text}")
                    # Try to get more specific error info
                    try:
                        error_data = response.json()
                        print(f"Error details: {error_data}")
                    except:
                        pass
                    break

                data = response.json()
                items = data.get('items', [])

                if not items:
                    break

                print(f"Processing {len(items)} tracks...")

                # Add tracks to playlist manager
                track_ids = []
                for item in items:
                    track = item['track']
                    if track:  # Sometimes tracks can be null
                        song = playlist_manager.add_song(track)
                        # Set date_added from Spotify data
                        song.date_added = datetime.fromisoformat(item['added_at'].replace('Z', '+00:00')).replace(
                            tzinfo=None)
                        track_ids.append(track['id'])

                # Fetch audio features for this batch
                if track_ids:
                    self._update_audio_features(playlist_manager, track_ids)

                    # Fetch artist data for genres
                    self._update_genres(playlist_manager, items)

                total_tracks += len(track_ids)
                offset += limit

                # Small delay to be polite to API

                time.sleep(0.1)

            print(f"Loaded {total_tracks} liked songs")
            return playlist_manager

        except Exception as e:
            print(f"Error retrieving liked songs: {e}")
            return playlist_manager

    def merge_playlist_data(self, playlist_manager: PlaylistManager, playlist_name_or_id: str):
        """Update PlaylistManager with fresh data from a specific playlist"""
        try:
            # Handle both playlist names and IDs
            if playlist_name_or_id == "liked_songs":
                # Special case for liked songs
                fresh_data = self.get_liked_songs(playlist_manager.audio_features_to_track)

                # Merge preserving user ratings
                for spotify_id, fresh_song in fresh_data.items():
                    if spotify_id in playlist_manager:
                        # Preserve existing user data but update metadata
                        existing_song = playlist_manager[spotify_id]
                        existing_song.update_from_spotify({
                            'name': fresh_song.name,
                            'artists': [{'name': fresh_song.artist}],
                            'album': {'name': fresh_song.album},
                            'id': spotify_id
                        })
                        existing_song.audio_features.update(fresh_song.audio_features)
                        existing_song.genres.update(fresh_song.genres)
                    else:
                        # Add new song
                        playlist_manager[spotify_id] = fresh_song

            else:
                # Handle regular playlists (implement if needed)
                print("Regular playlist syncing not yet implemented")

        except Exception as e:
            print(f"Error merging playlist data: {e}")

    def create_playlist_from_ids(self, name: str, track_ids: List[str], description: str = "") -> Optional[Dict]:
        """Create a new Spotify playlist with the given track IDs"""
        try:
            # Create playlist
            playlist = self.create_playlist(name, description, public=False)

            if not playlist:
                print("Failed to create playlist")
                return None
            if not track_ids:
                print("Creating Empty playlist")
            # Add tracks (API handles batching internally)
            track_uris = [f"spotify:track:{track_id}" for track_id in track_ids]
            success = self.add_tracks_to_playlist(playlist['id'], track_uris)

            if success:
                print(f"Created playlist '{name}' with {len(track_ids)} tracks")
                print(f"{playlist['external_urls']['spotify']}")
                return playlist
            else:
                print("Failed to add tracks to playlist")
                return None

        except Exception as e:
            print(f"Error creating playlist: {e}")
            return None

    def _update_audio_features(self, playlist_manager: PlaylistManager, track_ids: List[str]):
        """Helper to fetch and update audio features for a batch of tracks"""
        try:
            if not track_ids:
                return

            features_list = self.get_track_features(track_ids)

            if not features_list:
                # If no features returned (403 error), skip audio feature updates
                print("Skipping audio features due to API restrictions")
                return

            for features in features_list:
                if features and features.get('id') in playlist_manager:
                    playlist_manager[features['id']].update_audio_features(features)

        except Exception as e:
            print(f"Error updating audio features: {e}")

    def _update_genres(self, playlist_manager: PlaylistManager, track_items: List[Dict]):
        """Helper to fetch artist data and update genres"""
        try:
            # Extract unique artist IDs
            artist_ids = set()
            track_to_artists = {}

            for item in track_items:
                track = item['track']
                track_id = track['id']
                artist_id = track['artists'][0]['id']  # Primary artist
                artist_ids.add(artist_id)
                track_to_artists[track_id] = artist_id

            # Fetch artist data in batches of 50
            artist_ids = list(artist_ids)
            for i in range(0, len(artist_ids), 50):
                batch = artist_ids[i:i + 50]
                ids_str = ','.join(batch)

                response = self._make_api_request(f'artists?ids={ids_str}')

                if response.status_code == 200:
                    artists_data = response.json()
                    artist_genres = {}

                    for artist in artists_data.get('artists', []):
                        if artist:  # Sometimes null artists in response
                            artist_genres[artist['id']] = artist.get('genres', [])

                    # Update songs with genre data
                    for track_id, artist_id in track_to_artists.items():
                        if track_id in playlist_manager and artist_id in artist_genres:
                            playlist_manager[track_id].add_genres(artist_genres[artist_id])

        except Exception as e:
            print(f"Error updating genres: {e}")


def update():
    # Initialize and authenticate Spotify API
    spotify_api = SpotifyPlaylistAPI()

    if not spotify_api.authenticate():
        print("Failed to authenticate with Spotify")
        # return

    # Initialize playlist manager with desired audio features
    my_music = PlaylistManager("my_music.json")

    # Sync with liked songs (this will take a while for large libraries)
    print("Syncing with liked songs...")
    spotify_api.merge_playlist_data(my_music, "liked_songs")

    # Save the data
    my_music.save_to_json()


def main(pull_liked=False):
    """Just Shuffle"""
    # Initialize and authenticate Spotify API
    spotify_api = SpotifyPlaylistAPI()
    spotify_api.authenticate()

    # Initialize playlist manager with desired audio features
    my_music = PlaylistManager("my_music.json")
    if not my_music or pull_liked:  # Not found
        # Sync with liked songs (this will take a while for large libraries)
        print("Syncing with liked songs...")
        spotify_api.merge_playlist_data(my_music, "liked_songs")
        my_music.save_to_json()

    # Just shuffle it
    selected_tracks = []
    for song_id, song in my_music.items():
        selected_tracks.append(song_id)

    # Limit to 1000 tracks and create playlist
    random.shuffle(selected_tracks)
    playlist_tracks = selected_tracks[:1000]
    spotify_api.create_playlist_from_ids(
        f"Liked Shuffle all",
        playlist_tracks,
        f"Generated playlist with {len(playlist_tracks)} Songs")


def exp_star(song, b=2):
    """Exponential star weight"""
    return b ** (song.stars - 5)


def exp_star_recent(song, b, days_back=365, weight_day=0.01):
    """Exponential star weight, linear weight for time from cutoff"""
    days = (datetime.now() - song.date_added).days
    if song.stars == 5 and days < days_back:
        return exp_star(song, b) + (days_back - days) * weight_day
    else:
        return exp_star(song, b)


def binary_search_weight(cumulative_weights, target):
    """
    Find the leftmost index where cumulative_weights[index] > target
    """
    left = 0
    right = len(cumulative_weights)
    while left < right:
        mid = (left + right) // 2

        if cumulative_weights[mid] > target:
            right = mid  # Could be the answer, keep searching left
        else:
            left = mid + 1  # Target is bigger, search right

    return left


def weight_cdf_shuffle(fun=exp_star, notlast=100, kwargs={'b': 2}):
    """Shuffle, with weight function"""
    # Initialize and authenticate Spotify API
    spotify_api = SpotifyPlaylistAPI()
    spotify_api.authenticate()

    my_music = PlaylistManager("my_music.json")

    weights = []
    sums = [0]
    song_ids = list(my_music.keys())
    for song_id, song in my_music.items():
        weight = fun(song, **kwargs)
        weights.append(weight)
        sums.append(weight + sums[-1])
    total_weight = sum(weights)
    sums.pop(0)
    sums = [s / total_weight for s in sums]

    selected_tracks = []

    for ii in range(1000):
        rnd = random.random()
        index = binary_search_weight(sums, rnd)
        song_id = song_ids[index]
        max_back = min([ii,notlast])
        if notlast==0:
            pass
        elif song_id in selected_tracks[-max_back:]:
            continue
        selected_tracks.append(song_id)

    # Limit to 1000 tracks and create playlist
    random.shuffle(selected_tracks)
    playlist_tracks = selected_tracks[:1000]
    spotify_api.create_playlist_from_ids(
        f"Liked Weighted",
        playlist_tracks,
        f"Generated playlist with {len(playlist_tracks)} Songs")


if __name__ == "__main__":
    main()
    # update()
    # weight_cdf_shuffle()
    # weight_cdf_shuffle(exp_star_recent,200,{'b':2})
