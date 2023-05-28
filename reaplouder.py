from pytube import YouTube
import os
import glob
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload
import atexit
import time

def cleanup():
    # Delete the video file
    video_filenames = glob.glob("*.mp4")
    for file in video_filenames:
        os.remove(file)

def saveFailedLinks():
    if len(failedLinks) > 0:
        with open("failedLinks", "w") as file:
            file.write("\n".join(failedLinks))
        print("Failed links saved to file: failedLinks")
atexit.register(saveFailedLinks)
atexit.register(cleanup)

# set up the YouTube API
# Define the OAuth scopes required for accessing the YouTube Data API
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]

# Path to the OAuth credentials JSON file obtained from the Google Cloud Console
CLIENT_SECRETS_FILE = "secret.json"

# Set up the OAuth flow
flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
credentials = flow.run_local_server()

# Build the YouTube Data API client
api_service_name = "youtube"
api_version = "v3"
youtube = build(api_service_name, api_version, credentials=credentials)


# have a place of links that failed
failedLinks = []

def _makePlaylist(playlist_title, playlist_description):
    """
    Creates a yt playlist and returns its id
    """
    playlist_request_body = {
        "snippet": {
            "title": playlist_title,
            "description": playlist_description
        },
        "status": {
            "privacyStatus": "private"
        }
    }
    playlist_response = youtube.playlists().insert(
        part="snippet,status",
        body=playlist_request_body
    ).execute()
    playlist_id = playlist_response["id"]
    print("Created playlist:", playlist_title)
    return playlist_id

def _uploadSingleVid(video_filename, video_name, video_description, link, playlist_id):
    ## Upload video to YouTube as unlisted
    request_body = {
        "snippet": {
            "title": video_name,
            "description": video_description,
            "categoryId": "27"  # Set the appropriate category ID for your video, 27 is Education
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False
        }
    }

    response = None
    media = MediaFileUpload(video_filename, chunksize=4*1024*1024, resumable=True)
    while response is None:
        try:
            response = youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media
            ).execute()
            video_id = response["id"]
            unlisted_video_link = f"https://youtu.be/{video_id}"
            print("Uploaded video:", unlisted_video_link)
            
            playlist_item_request_body = {
                "snippet": {
                    "playlistId": playlist_id,
                    "position": 0,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id
                    }
                }
            }
            youtube.playlistItems().insert(
                part="snippet",
                body=playlist_item_request_body
            ).execute()
            print("Added video to playlist:", video_name)
        except Exception as e:
            if "HttpError 404" in str(e):
                # Chunk upload failed, retry
                print("Chunk upload failed. Retrying...")
                continue
            elif "quota" in str(e):
                # oh boy we hit daily quota already
                print("Daily quota exceeded. going to sleep for 24 hours")
                time.sleep(24*60*60)
                continue
            else:
                # Handle other exceptions
                print("Error uploading video:", e)
                failedLinks.append(link)
                break


def reuploadFromSeparateVidLinks(playlist_title, playlist_description):

    # create a playlist
    playlistID = _makePlaylist(playlist_title, playlist_description)

    # Read the text file containing video links
    with open("vidlinks", "r") as file:
        video_links = file.read().splitlines()

    ## Download videos using pytube
    for link in video_links:
        maxRetries = 100
        retries = 0
        while retries < maxRetries:
            try:
                video = YouTube(link)
                video_title = video.title
                video_description = video.description
                highres = video.streams.get_highest_resolution()
                highres.download()
            except Exception as e:
                print("Error downloading video:", e , " retrying...")
                retries += 1
            else:
                break

        if retries == maxRetries:
            failedLinks.append(link)
            print("Failed to download video:", link)
            continue

        print("downloaded video:", video_title)

        # get the vid name *.mp4
        video_filename = glob.glob("*.mp4")[0]
        
        # upload vid
        _uploadSingleVid(video_filename, video_title, video_description, link, playlistID)
            
        # Delete the video file
        os.remove(video_filename)


def reuploadFromExistingPlaylists():
    """
    Reuploads videos from existing playlists. It will reuse the original playlist's titles and descriptions.
    """

    # get all playlists from file
    with open("playlistlinks", "r") as file:
        playlist_links = file.read().splitlines()

    for playlist_link in playlist_links:
        # get playlist id from link
        PlaylistID = playlist_link.split("list=")[1]
        playlist_items = youtube.playlistItems().list(
            part="snippet",
            playlistId=PlaylistID,
            maxResults=50
        ).execute()

        playlist_title = playlist_items["items"][0]["snippet"]["title"]
        playlist_description = playlist_items["items"][0]["snippet"]["description"]

        # get all video links
        video_links = []
        for item in playlist_items["items"]:
            video_links.append(f"https://youtu.be/{item['snippet']['resourceId']['videoId']}")

        # create own playlist
        
        ownPlaylistID = _makePlaylist(playlist_title, playlist_description)

        ## Download videos using pytube
        for link in video_links:
            maxRetries = 100
            retries = 0
            while retries < maxRetries:
                try:
                    video = YouTube(link)
                    video_title = video.title
                    video_description = video.description
                    highres = video.streams.get_highest_resolution()
                    highres.download()
                except Exception as e:
                    print("Error downloading video:", e , " retrying...")
                    retries += 1
                else:
                    break

            if retries == maxRetries:
                failedLinks.append(link)
                print("Failed to download video:", link)
                continue

            print("downloaded video:", video_title)

            # get the vid name *.mp4
            video_filename = glob.glob("*.mp4")[0]
            
            # upload vid
            _uploadSingleVid(video_filename, video_title, video_description, link, ownPlaylistID)
                
            # Delete the video file
            os.remove(video_filename)




if __name__ == "__main__":

    playlist_title = "Principy počítačů (NSWI120)"
    playlist_description = "Záznam přednášek z roku 2020/2021. Přednáší Pavel Ježek."

    reuploadFromSeparateVidLinks(playlist_title, playlist_description)