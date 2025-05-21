import json
import os
import re
import time
from urllib.parse import parse_qs, urlparse

import dropbox
import requests
from dropbox.exceptions import ApiError
from tqdm import tqdm

# Dropbox app credentials - replace these with your actual credentials
APP_KEY = "YOUR_APP_KEY"
APP_SECRET = "YOUR_APP_SECRET"


def get_oauth2_flow():
    """
    Get OAuth2 flow for Dropbox authentication
    """
    auth_flow = dropbox.DropboxOAuth2FlowNoRedirect(APP_KEY, APP_SECRET)
    return auth_flow


def load_credentials():
    """
    Load saved credentials from file
    """
    try:
        with open("dropbox_credentials.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_credentials(credentials):
    """
    Save credentials to file
    """
    with open("dropbox_credentials.json", "w") as f:
        json.dump(credentials, f)


def get_dropbox_client():
    """
    Get or refresh Dropbox client with OAuth2
    """
    credentials = load_credentials()

    if credentials is None:
        # First time setup
        auth_flow = get_oauth2_flow()
        authorize_url = auth_flow.start()
        print("1. Go to: " + authorize_url)
        print("2. Click 'Allow' (you might have to log in first)")
        print("3. Copy the authorization code")
        auth_code = input("Enter the authorization code here: ").strip()

        try:
            oauth_result = auth_flow.finish(auth_code)
            credentials = {
                "access_token": oauth_result.access_token,
                "refresh_token": oauth_result.refresh_token,
            }
            save_credentials(credentials)
        except Exception as e:
            print(f"Error: {e}")
            return None

    # Create Dropbox client with refresh token
    try:
        return dropbox.Dropbox(
            oauth2_refresh_token=credentials["refresh_token"],
            app_key=APP_KEY,
            app_secret=APP_SECRET,
        )
    except Exception as e:
        print(f"Error creating Dropbox client: {e}")
        return None


def download_dropbox_folder(dbx, shared_link, current_path, local_root, dropbox_root):
    """
    Recursively download files from a Dropbox shared link folder

    Args:
        dbx: Dropbox client instance
        shared_link: The shared link URL
        current_path: Current path in Dropbox
        local_root: Local root path to save the files
        dropbox_root: The root path of the Dropbox share
    """
    try:
        shared_link_obj = dropbox.files.SharedLink(url=shared_link)
        list_path = "" if current_path is None else current_path
        result = dbx.files_list_folder(path=list_path, shared_link=shared_link_obj)
        while True:
            for entry in result.entries:
                # Always construct the full Dropbox path
                if current_path in (None, "", "/"):
                    full_path = f"/{entry.name}"
                else:
                    full_path = f"{current_path.rstrip('/')}/{entry.name}"

                # Compute local path relative to Dropbox root
                if dropbox_root in (None, "", "/"):
                    rel_path = full_path.lstrip("/")
                else:
                    rel_path = os.path.relpath(full_path, dropbox_root)
                local_file_path = os.path.join(local_root, rel_path)

                print(
                    f"Processing entry: {entry.name} at path: {full_path} (local: {local_file_path})"
                )

                if isinstance(entry, dropbox.files.FileMetadata):
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    try:
                        # Extract rlkey from shared link
                        parsed_url = urlparse(shared_link)
                        query_params = parse_qs(parsed_url.query)
                        rlkey = query_params.get("rlkey", [None])[0]

                        if rlkey:
                            # Construct direct download URL
                            file_url = f"https://www.dropbox.com/scl/fi/{entry.id}/{entry.name}?dl=1&rlkey={rlkey}"

                            # Download with progress bar
                            response = requests.get(file_url, stream=True)
                            response.raise_for_status()

                            total_size = int(response.headers.get("content-length", 0))
                            with open(local_file_path, "wb") as f, tqdm(
                                desc=entry.name,
                                total=total_size,
                                unit="iB",
                                unit_scale=True,
                                unit_divisor=1024,
                            ) as pbar:
                                for data in response.iter_content(chunk_size=1024):
                                    size = f.write(data)
                                    pbar.update(size)
                            print(f"Downloaded: {full_path}")
                        else:
                            # Fallback to API download if rlkey not found
                            dbx.files_download_to_file(local_file_path, entry.id)
                            print(f"Downloaded: {full_path}")
                    except Exception as e:
                        print(f"Error downloading {full_path}: {e}")
                        if isinstance(e, ApiError) and e.error.is_rate_limit():
                            time.sleep(2)
                            try:
                                dbx.files_download_to_file(local_file_path, entry.id)
                                print(f"Retry successful: {full_path}")
                            except ApiError as e2:
                                print(f"Retry failed for {full_path}: {e2}")
                elif isinstance(entry, dropbox.files.FolderMetadata):
                    download_dropbox_folder(
                        dbx, shared_link, full_path, local_root, dropbox_root
                    )
            if not result.has_more:
                break
            result = dbx.files_list_folder_continue(result.cursor)
    except Exception as e:
        print(f"Error processing folder {current_path}: {e}")


def main():
    # Get Dropbox client with OAuth2
    dbx = get_dropbox_client()
    if dbx is None:
        print("Failed to initialize Dropbox client")
        return

    # Dropbox shared link
    SHARED_LINK = "YOUR_DROPBOX_SHARED_LINK?rlkey=SOME_RLKEY"

    # Local path to save the files
    LOCAL_SAVE_PATH = "downloaded_files"

    # For shared links, the root is always ""
    dropbox_root = ""

    print(f"Starting download from shared link: {SHARED_LINK}")
    print(f"Dropbox root: {dropbox_root}")
    print(f"Saving files to: {LOCAL_SAVE_PATH}")

    try:
        download_dropbox_folder(dbx, SHARED_LINK, None, LOCAL_SAVE_PATH, dropbox_root)
        print("Download completed successfully!")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
