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

# have a place of links that failed
failedLinks = []

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


def reuploadFromSeparateVidLinks(playlist_title, playlist_description, source = "vidlinks"):
    """
    Reuploads videos from a text file containing video links. It will create a new playlist and upload the videos there.
    """
    # create a playlist
    playlistID = _makePlaylist(playlist_title, playlist_description)

    # Read the text file containing video links
    with open(source, "r") as file:
        video_links = file.read().splitlines()

    ## Download videos using pytube
    try:
        for i, link in enumerate(video_links):
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
    except Exception as e:
        # someting happened, save remaining links to file
        with open("remainingLinks", "w") as file:
            file.write("\n".join(video_links[i:]))
        print("Remaining links saved to file: remainingLinks")
        raise e

def reuploadFromExistingPlaylists():
    """
    Reuploads videos from existing playlists. It will reuse the original playlist's titles and descriptions.
    """

    # get all playlists from file
    with open("playlistlinks", "r") as file:
        playlist_links = file.read().splitlines()

    try:
        for i, playlist_link in enumerate(playlist_links):
            # get playlist id from link
            PlaylistID = playlist_link.split("list=")[1]

            # get playlist title and description
            playlistInfo = youtube.playlists().list(
                part="snippet",
                id=PlaylistID
            ).execute()

            playlist_title = playlistInfo["items"][0]["snippet"]["title"]
            playlist_description = playlistInfo["items"][0]["snippet"]["description"]

            # and now the videos
            playlist_items = youtube.playlistItems().list(
                part="snippet",
                playlistId=PlaylistID,
                maxResults=50
            ).execute()

            video_links = []
            for item in playlist_items["items"]:
                video_links.append(f"https://youtu.be/{item['snippet']['resourceId']['videoId']}")

            # create own playlist
            
            ownPlaylistID = _makePlaylist(playlist_title, playlist_description)

            ## Download videos using pytube
            try:
                for j, link in enumerate(video_links):
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
            except Exception as e:
                # someting happened, save remaining links to file
                with open("remainingLinks", "w") as file:
                    file.write("\n".join(video_links[j:]))
                print("Remaining links saved to file: remainingLinks")
                raise e
    except Exception as e:
        # someting happened, save remaining playlists to file
        with open("remainingPlaylists", "w") as file:
            file.write("\n".join(playlist_links[i:]))
        print("Remaining playlists saved to file: remainingPlaylists")
        raise e
        




if __name__ == "__main__":

    playlist_title = "Principy počítačů (NSWI120)"
    playlist_description = "Záznam přednášek z roku 2020/2021. Přednáší Pavel Ježek."
    reuploadFromSeparateVidLinks(playlist_title, playlist_description, source = "principyPocitacu")

    playlist_title = "Jazyk C# a platforma .NET (NPRG035) Přednáška"
    playlist_description = "Záznam přednášek z roku 2020/2021. Přednáší Pavel Ježek."
    reuploadFromSeparateVidLinks(playlist_title, playlist_description, source = "csharp")

    playlist_title = "Jazyk C# a platforma .NET (NPRG035) Cvičení"
    playlist_description = "Záznam cvičení z roku 2020/2021. Přednáší Pavel Ježek."
    reuploadFromSeparateVidLinks(playlist_title, playlist_description, source = "ccvik")

    playlist_title = "Language C# a platform .NET (NPRG035) Lecture"
    playlist_description = "Recording of lectures from years 2020/2021. Given by Pavel Ježek."
    reuploadFromSeparateVidLinks(playlist_title, playlist_description, source = "ceng")

    reuploadFromExistingPlaylists()