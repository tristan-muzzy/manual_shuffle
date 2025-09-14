# manual_shuffle
Spotify API calls to make custom playlists

This codes API calling class was written by Claude Sonnet 4, with no proofreading
I designed the PlaylistManager and Song class design, with proofreading and modification

Known Bugs:
    The audio features fails to update. Not sure of this is my account issue or syntax

Setup:
1.     Go to https://developer.spotify.com/dashboard
2.     Click "Create app"
3.     Fill in your app details
4.     Important: Set the redirect URI to: http://127.0.0.1:8000/callback
5.     Save your Client ID and Client Secret
6.     Create a secret.txt file in this directory with the following format (in gitignore to prevent accidental sharing)
            CLIENT_ID = 123456789qwertyuiop
            CLIENT_SECRET = asdfghjklzxcvbnm987654321

Use:
1.     Run the src.py script. This should authenticate in browser in every run.
2.     The first call will create a 'my_music.json' in this directory based on liked songs. (other playlist IDs can be entered)
3.     Future calls will preserve manually changed information and pull in new songs
4.     The "main()" function calls an update and makes a plain shuffle playlist
5.     The "update()" function just updates from liked songs
6.     The "weight_cdf_shuffle()" uses the 'my_music.json' file to make a playlist weighted as a function of Song attributes.
           By defualt, stars=5 is unweighted, 6 is 2x, 7 is 4x, 4 is 1/2x, 3 is 1/4x and so on, with the exponent 'b' is adjustable
           Any function taking a Song object + kwargs may be used
           Also shown is a linear time weight falloff function




Good Luck, Have Fun

- Tristan Muzzy