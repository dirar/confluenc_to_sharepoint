import json
import os
import mimetypes
import msal
import uuid
import logging
from pydoc import isdata
from bs4 import BeautifulSoup
from fileinput import filename
from numpy import delete
from office365.sharepoint.attachments.attachmentfile_creation_information import AttachmentfileCreationInformation
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.files import file
from office365.sharepoint.files.file import File
from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.listitems.caml.caml_query import CamlQuery
from configparser import ConfigParser

class ConfluencToSharePoint():
        
    def __init__(self, settings_file):
        """
        Initializes the ConfluenceToSharePoint class with settings from the provided file.

        This method sets up the connection to SharePoint using the provided credentials
        and settings. It also retrieves the specified SharePoint list and initializes
        other required attributes.

        Parameters:
        - settings_file (str): Path to the settings file that contains configuration details.

        Attributes:
        - settings_file (str): Stores the path to the settings file.
        - settings (ConfigParser): Configuration settings loaded from the settings file.
        - site_url (str): URL of the SharePoint site.
        - list_name (str): Name of the SharePoint list to interact with.
        - assets_folder (str): Path to the assets folder.
        - client_credentials (ClientCredential): SharePoint client credentials.
        - ctx (ClientContext): Client context for interacting with the SharePoint site.
        - ll_list: The SharePoint list object.
        - windows_path (dict): Windows paths evaluated from settings.
        - site: The SharePoint site object.
        - web: The root web of the SharePoint site.

        Raises:
        - Exception: If there is an error setting up client credentials or querying the site.
        """
        self.settings_file = settings_file
        self.settings = self.load_settings()
        self.site_url = self.settings.get('default', 'site_url')
        self.list_name = self.settings.get('default', 'list_name')
        self.assets_folder = self.settings.get('default', 'assets_folder')

        try:
            self.client_credentials = ClientCredential(
                self.settings.get('client_credentials', 'client_id'),
                self.settings.get('client_credentials', 'client_secret')
            )
            self.ctx = ClientContext(self.site_url).with_credentials(self.client_credentials)        
            self.ll_list = self.ctx.web.lists.get_by_title(self.list_name).get().execute_query()
            self.windows_path = eval(self.settings.get('default', 'windows_path'))
            self.site = self.ctx.site.get().execute_query()
            self.web = self.ctx.site.root_web.get().execute_query()
        except Exception as e:
            if 'AADSTS700016' in str(e):
                self.print_error("Error: Application with identifier was not found in the directory.")
                self.print_error("Please check the client ID and client secret.")
            else:
                self.print_error(f"An unexpected error occurred while setting up client credentials: {e}")            
            raise

    def load_settings(self):
        """
        Loads settings from the provided settings file.

        This method reads the configuration settings from the specified file and returns
        a ConfigParser object containing the settings.

        Returns:
        - config (ConfigParser): The configuration settings.

        Raises:
        - FileNotFoundError: If the settings file does not exist.
        - configparser.Error: If there is an error reading the configuration file.
        """
        try:
            config = ConfigParser()
            root_dir = os.path.dirname(os.path.abspath(__file__))
            config_file = os.path.join(root_dir, self.settings_file)
            if not os.path.exists(config_file):
                self.print_error(f"Settings file {config_file} not found.")
                raise
            config.read(config_file)
            return config
        except FileNotFoundError as e:
            self.print_error(f"Error: {e}")
            raise
        except config.Error as e:
            self.print_error(f"Error reading the configuration file: {e}")
            raise    
    
    def parse_confluence_HTML(self, path, sp_fields, elements_to_remove = []):
        """
        Parses the HTML files in the specified path to extract content from Confluence pages
        and uploads the information to SharePoint.

        This method checks if the specified path and its index.html file exist, then processes
        each page in the directory, extracting relevant information and uploading attachments.

        Parameters:
        - path (str): The directory path containing Confluence HTML files.
        - sp_fields (dict): SharePoint fields to map data to.
        - elements_to_remove (list): A list of HTML elements to remove from the parsed content.

        Returns:
        - None: Returns None upon successful completion.

        Raises:
        - FileNotFoundError: If the specified path does not exist or if index.html is missing.
        - Exception: If an error occurs during file processing or uploading to SharePoint.
        """
        try:
            if not os.path.exists(path) or not os.path.isfile(f"{path}index.html"):
                self.print_error("Path not found. Check the path name and try again.")
                raise

            with open(f"{path}index.html") as fp:
                soup = BeautifulSoup(fp, 'html.parser')
                #get page title
                pageInfo = soup.select(".confluenceTable td")
                mainTitle = pageInfo[1].text if len(pageInfo) > 0 else ''
                pageSection = soup.select(".pageSection li")            
                #get css
                css_path = f"{path}styles\\site.css" if self.windows_path else f"{path}styles/site.css"
                css_file = ""
                css_str = ""
                if os.path.exists(css_path):
                    css_file = open(css_path,"r")
                    #css_str = f"<style type='text/css'>{compress(css_file.read())}</style>"                

                for page in pageSection:
                    #page names includes whitespace
                    page_link = page.select_one("a")
                    page_title = ' '.join( page_link.text.split())
                    page_name = f"{page_title}"#{mainTitle}_
                    page_file = page_link.attrs["href"]
                    self.print_message(f"Processing {page_name}...")
                    if os.path.isfile(f"{path}{page_file}"):
                        with open(f"{path}{page_file}", encoding="utf-8") as fp2:#get page attachments
                            page_soup = BeautifulSoup(fp2, "html.parser")
                            main_content = page_soup.select_one("#main-content")
                            if len(main_content.contents) == 0 or len(main_content.text.rstrip()) == 0 : continue #if empty continue and don't import
                            attachments = page_soup.select("div.pageSection .greybox a")
                            page_author = page_soup.select_one(".author")
                            page_author_name = ""
                            if page_author: page_author_name = page_author.text
                            user = self.getSiteUser(page_author_name)
                            page_author_object = user  
                            #remove containers by class name
                            if len(elements_to_remove) > 0:
                                self.remove_elements(page_soup, elements_to_remove)
                            if len(attachments) > 0 :
                                self.uploadPageAttachment(path, attachments)
                            #fix images path
                            attachments_obj = main_content.find_all(attrs={"data-linked-resource-type": "attachment"})
                            if len(attachments_obj) > 0:
                                self.fixAttachmentsPath(attachments_obj)
                            #fix anchors
                            links = main_content.find_all("a", href=True) 
                            if len(links) > 0:
                                self.fixAnchors(links, main_content)
                            page_html = css_str + str(main_content)                        
                            page_canvas = self.getSPPageCanvas(main_content)
                            if page_canvas == None:
                                self.print_error("Issue creating Page Canvas!")
                                return None
                            #Create Page
                            page_canvas_json = json.dumps(page_canvas)
                            page = self.add_edit_page(page_name, page_canvas_json, page_author_object, sp_fields)                        
                            links = main_content.find_all("a", href=True)                        
                            #log file contains all link, might need to be replaced
                            if len(links) > 0:
                                self.logLinks(links, page["url"])
                            #rename file to mark as complete          
                            self.print_message(f"Completed {page_file}")
                            fp2.close
                        os.rename(f"{path}{page_file}",f"{path}{page_file}_complete")
                        self.print_message(f"{page_file} renamed to {page_file}_complete")
                #print(pageSection)
                self.print_message(f"Done!")
            return True
        except FileNotFoundError as e:
            self.print_error(f"Error: {e}")
            return False
        except Exception as e:
            self.print_error(f"An unexpected error occurred: {e}")
            return False

    def getSiteUser(self, full_name):
        """
        Retrieves a SharePoint site user based on the provided full name.

        This method filters the site users by the given full name and loads the user data
        from SharePoint. If a matching user is found, it returns the user object; otherwise,
        it returns None.

        Parameters:
        - full_name (str): The full name of the user to search for.

        Returns:
        - User object if found, None otherwise.

        Raises:
        - Exception: If an error occurs while executing the query.
        """
        try:
            full_name = full_name.strip()
            if full_name == "":
                self.print_error("Full name cannot be empty.")
                return None

            users = self.ctx.web.site_users.filter(f"title eq '{full_name}'")
            self.ctx.load(users)
            self.ctx.execute_query()

            if len(users) > 0:
                return users[0]
            else:
                self.print_message("No user found with the specified full name.")
                return None

        except Exception as e:
            self.print_error(f"An error occurred while retrieving the user: {e}")
            return None

    def remove_elements(self, page, elements_to_remove):
        """
        Removes specified HTML elements from the given BeautifulSoup page object.

        This method takes a list of class names and removes all corresponding elements 
        from the parsed HTML page.

        Parameters:
        - page (BeautifulSoup object): The BeautifulSoup object representing the HTML page.
        - elements_to_remove (list): A list of class names for elements to be removed.

        Returns:
        - None: The method modifies the page in place and does not return any value.

        Raises:
        - Exception: If an error occurs during element removal.
        """
        try:
            for element_to_remove in elements_to_remove:
                elements = page.select(f".{element_to_remove}")
                for element in elements:
                    element.decompose()  # Remove the element from the tree
                    self.print_message(f"Removed element: {element_to_remove}")

        except Exception as e:
            self.print_error(f"An error occurred while removing elements: {e}")

    def uploadPageAttachment(self, path, attachments):
        """
        Uploads page attachments to SharePoint based on the provided list of attachment links.

        This method iterates through the specified attachments, checks if the corresponding
        files exist in the given path, and collects the valid file paths for uploading. 
        If any attachments are found, it calls the `add_attachments` method to perform the upload.

        Parameters:
        - path (str): The directory path where the attachment files are located.
        - attachments (list): A list of attachment HTML elements containing file links.

        Returns:
        - bool: Returns True if the upload process is initiated successfully; otherwise, returns False.

        Raises:
        - Exception: If an error occurs during file checking or uploading.
        """
        try:
            attachments_arr = []
            page_name = ""
            for attachment in attachments:
                attachment_file = attachment.attrs["href"]
                file_name = os.path.join(path, attachment_file)
                
                if os.path.isfile(file_name):
                    page_name = page_name if page_name != "" else os.path.dirname(attachment_file)
                    attachments_arr.append(file_name.replace("/", "\\") if self.windows_path else file_name)

            if attachments_arr:
                self.add_attachments(attachments_arr, page_name)
                self.print_message(f"Uploaded {len(attachments_arr)} attachments for page: {page_name}")
            else:
                self.print_message("No valid attachments found for upload.")

            return True

        except Exception as e:
            self.print_error(f"An error occurred while uploading attachments: {e}")
            return False

    def add_attachments(self, files_to_add, page_folder = None, overwrite = False):
        """
        Uploads specified files to a SharePoint folder, with options to check for existing files
        and whether to overwrite them.

        This method checks if each file in the provided list exists on the local file system.
        If the file exists, it checks if a file with the same name already exists in the target
        SharePoint folder. Depending on the `overwrite` parameter, it either uploads the file or 
        skips the upload if a file with the same name already exists.

        Parameters:
        - files_to_add (list): A list of file paths to be uploaded to SharePoint.
        - page_folder (str, optional): The folder within SharePoint where files should be uploaded.
        - overwrite (bool, optional): Whether to overwrite existing files with the same name.

        Returns:
        - dict: A dictionary containing the upload status for each file.

        Raises:
        - Exception: If an error occurs during file checking or uploading.
        """
        result = {}
        size_chunk = 1000000
        
        try:
            # Ensure the target folder exists
            target_folder = self.ctx.web.ensure_folder_path(self.assets_folder + "/" + (page_folder or "")).execute_query()
            folder_files = target_folder.files.get().execute_query()

            for path in files_to_add:
                result[path] = {}
                if not os.path.exists(path):
                    result[path]["result"] = "Not uploaded: File not found. Check the file name and try again"
                    continue
                
                filename = os.path.basename(path)
                file = folder_files.filter(f"Name eq '{filename}'").get().execute_query()

                if len(file._data) > 0:
                    if not overwrite:
                        result[path]["result"] = "Not uploaded: File exists and overwrite is set to false"
                        result[path]["name"] = file._data[0].name
                        result[path]["serverRelativeUrl"] = file._data[0].serverRelativeUrl
                        continue
                
                with open(path, 'rb') as fh:
                    file_content = fh.read()
                    print(f"Uploading {filename}...")
                    target_file = target_folder.upload_file(filename, file_content).execute_query()
                    result[path]["result"] = "File upload completed"
                    result[path]["name"] = target_file.name
                    result[path]["serverRelativeUrl"] = target_file.serverRelativeUrl

            return result

        except Exception as e:
            self.print_error(f"An error occurred while adding attachments: {e}")
            return {file: {"result": "Upload failed due to an error."} for file in files_to_add}

    def get_item(self, field, value):
        """
        Retrieves a specific item from the SharePoint list based on a field and its corresponding value.

        This method filters the items in the SharePoint list based on the specified field and value.
        If an item is found, it returns the properties of the first matching item; otherwise, it returns None.

        Parameters:
        - field (str): The name of the field to filter the items by.
        - value (str): The value to match against the specified field.

        Returns:
        - dict: The properties of the matching item if found; otherwise, None.

        Raises:
        - Exception: If an error occurs during the query execution.
        """
        try:
            ll_item = self.ll_list.items.get().filter(f"{field} eq '{value}'").execute_query()
            if len(ll_item._data) > 0:
                return ll_item._data[0].properties
            else:
                self.print_message("No matching item found.")
                return None

        except Exception as e:
            self.print_error(f"An error occurred while retrieving the item: {e}")
            return None

    def update_item(self, id, params):
        """
        Updates a specific item in the SharePoint list with the provided parameters.

        This method retrieves the item by its ID and updates its properties based on the 
        key-value pairs provided in the params dictionary. The updates are executed in a 
        batch to improve performance.

        Parameters:
        - id (int): The ID of the item to be updated.
        - params (dict): A dictionary containing the properties to update, with field names as keys 
                         and the corresponding new values.

        Returns:
        - dict: The result of the update operation.

        Raises:
        - Exception: If an error occurs during the update process.
        """
        try:
            item = self.ll_list.get_item_by_id(id)
            ll_item = item.get().execute_query()

            for k, v in params.items():
                ll_item.set_property(k, v)

            result = self.ctx.execute_batch()  # Execute the batch update
            return result

        except Exception as e:
            self.print_error(f"An error occurred while updating the item: {e}")
            raise

    def add_edit_page(self, page_name, page_canvas, author, sp_fields = [], attachments = [], page_id = None):
        """
        Adds or edits a page in the SharePoint site.

        This method either creates a new page or updates an existing page based on the provided page_id.
        It saves the page content, including the layout and author information, and publishes the page.
        
        Parameters:
        - page_name (str): The name of the page to be added or edited.
        - page_canvas (list): The content layout of the page in JSON format.
        - author (User): The author of the page, containing properties like Email and Title.
        - sp_fields (list): Optional fields to update in the SharePoint list.
        - attachments (list): Optional attachments to add to the page.
        - page_id (int): Optional ID of the page to be updated. If None, a new page will be created.

        Returns:
        - dict: Contains the ID, name, and URL of the page if successful; otherwise, None.

        Raises:
        - Exception: If an error occurs while adding or editing the page.
        """
        
        def create_page_query():
            qry = CamlQuery()
            qry.ViewXml = f"""
                <View Scope='RecursiveAll'>
                <Query>
                    <OrderBy  Override = "TRUE">
                        <FieldRef Name="Created" Ascending="FALSE"/>
                    </OrderBy>
                </Query>
                
                <QueryOptions><QueryThrottleMode>Override</QueryThrottleMode></QueryOptions>
                <RowLimit Paged='TRUE'>1</RowLimit>
            </View>
            """
            return qry

        try:
            if page_id is not None:
                page = self.ctx.site_pages.pages.get().filter(f"Id eq {page_id}").execute_query()
                if len(page._data) > 0:
                    site_page = page._data[0]
                    site_page.checkout_page().execute_query()
                else:
                    return None
            else:
                site_page = self.ctx.site_pages.pages.add()

            author_email = author.properties.get('Email', "") if author else ""
            author_title = author.properties.get('Title', "") if author else ""

            # Create empty canvas
            site_page.layout_web_parts_content = json.dumps([
                {
                    "id": "cbe7b0a9-3504-44dd-a3a3-0e5cacd07788",
                    "instanceId": "cbe7b0a9-3504-44dd-a3a3-0e5cacd07788",
                    "title": "Title area",
                    "description": "Title Region Description",
                    "audiences": [],
                    "serverProcessedContent": {"htmlStrings": {}, "searchablePlainTexts": {}, "imageSources": {}, "links": {}},
                    "dataVersion": "1.4",
                    "properties": {
                        "title": page_name,
                        "imageSourceType": 4,
                        "layoutType": "NoImage",
                        "textAlignment": "Left",
                        "showTopicHeader": 'false',
                        "showPublishDate": 'false',
                        "topicHeader": "",
                        "enableGradientEffect": 'true',
                        "authors": [{"id": author_email, "email": author_email, "name": author_title}],
                        "authorByline": [author_email]
                    },
                    "reservedHeight": 280
                },
                {
                    "id": "1ee8960a-2fa0-4145-b9bb-e818f6cf18e7",
                    "instanceId": "1ee8960a-2fa0-4145-b9bb-e818f6cf18e7",
                    "audiences": [],
                    "serverProcessedContent": {"htmlStrings": {}, "searchablePlainTexts": {}, "imageSources": {}, "links": {}},
                    "dataVersion": "1.0",
                    "properties": {
                        "hideWebPartWhenEmpty": 'true',
                        "isEditMode": 'true',
                        "isEnabled": 'false',
                        "layoutId": "FilmStrip",
                        "uniqueId": "e512b5d0-6873-472b-9819-b677d4a564bc",
                        "dataProviderId": "RecommendedItems"
                    },
                    "reservedHeight": 332
                }
            ])

            site_page.save_draft(page_name)
            site_page.publish().execute_query()

            # Retrieve page information after publishing
            if page_id is not None:
                item_page = self.ll_list.items.get().filter(f"Id eq {page_id}").execute_query()
            else:
                item_page = self.ll_list.get_items(create_page_query()).execute_query()

            page_id = None
            if len(item_page._data) > 0:
                data = item_page._data[0]
                file = data.file.get().execute_query()
                page_id = data.id
                page_url = file.serverRelativeUrl

                if sp_fields:
                    self.update_item(page_id, sp_fields)  # Update SharePoint fields if provided

                if attachments:
                    self.add_attachments(attachments, page_id)  # Add attachments if provided

                # Set page canvas and publish again
                site_page.checkout_page().execute_query()
                site_page.save_draft(page_name, page_canvas)
                site_page.publish().execute_query()

                return {"id": page_id, "name": page_name, "url": page_url}

        except Exception as e:
            self.print_error(f"An error occurred while adding or editing the page: {e}")
            raise

        return None
    
    def getSPPageCanvas(self, content):
        """
        Generates a structured representation of a SharePoint page canvas from the given HTML content.
        
        This method extracts all <img> tags from the provided content, constructs a corresponding 
        SharePoint widget for each image, and appends the resulting data to a canvas dictionary 
        which can be used to create or update a SharePoint page.

        Parameters:
            content (BeautifulSoup): The HTML content to process, containing <img> tags.

        Returns:
            list: A list of dictionaries representing the canvas components for SharePoint.

        Raises:
            ValueError: If no <img> tags are found in the content.
            Exception: If an unexpected error occurs during processing.
        """
        try:
            canvas_dict = []
            images = content.find_all("img")                        
            if len(images) > 0:
                for img in images:
                    guid = str(uuid.uuid4())
                    guid2 = str(uuid.uuid4())
                    guid3 = str(uuid.uuid4())
                    img_src = img['src']
                    
                    soup = BeautifulSoup(f"""<div tabindex='-1' data-cke-widget-wrapper='1' data-cke-filter='off'
                        class='cke_widget_wrapper cke_widget_block cke_widget_inlineimage cke_widget_wrapper_webPartInRteInlineImage cke_widget_wrapper_webPartInRteClear cke_widget_wrapper_webPartInRteAlignCenter cke_widget_wrapper_webPartInRte'
                        data-cke-display-name='div' data-cke-widget-id='5' role='region'
                        aria-label='Inline image in RTE. Use Alt + F11 to go to toolbar. Use Alt + P to open the property pane.'
                        contenteditable='' false''>
                        <div data-webpart-id='image'
                            class='webPartInRte webPartInRteAlignCenter webPartInRteClear webPartInRteInlineImage cke_widget_element'
                            data-cke-widget-data='%7B%22classes%22%3A%7B%22webPartInRteInlineImage%22%3A1%2C%22webPartInRteClear%22%3A1%2C%22webPartInRteAlignCenter%22%3A1%2C%22webPartInRte%22%3A1%7D%7D'
                            data-cke-widget-upcasted='1' data-cke-widget-keep-attr='0' data-widget='inlineimage'
                            data-instance-id='{guid}' title=''></div>
                        </div>
                        """, 'html.parser')
                    img.replace_with(soup)
                    
                    canvas_dict.append({
                        "position": {
                            "layoutIndex": 1,
                            "zoneIndex": 1,
                            "sectionIndex": 1,
                            "sectionFactor": 12,
                            "controlIndex": 0
                        },
                        "controlType": 3,
                        "id": guid,
                        "webPartId": "d1d91016-032f-456d-98a4-721247c305e8",
                        "rteInstanceId": "7802ec32-078a-42a7-b455-8eae2538781f",
                        "addedFromPersistedData":'true',
                        "reservedHeight": 160,
                        "reservedWidth": 1178,
                        "webPartData": {
                            "id": "d1d91016-032f-456d-98a4-721247c305e8",
                            "instanceId": guid,
                            "title": "Image",
                            "description": "Add an image, picture or photo to your page including text overlays and ability to crop and resize images.",
                            "audiences": [],
                            "serverProcessedContent": {
                                "htmlStrings": {},
                                "searchablePlainTexts": {},
                                "imageSources": {
                                    "imageSource": img_src
                                },
                                "links": {},
                                "customMetadata": {
                                    "imageSource": {
                                        "siteId": self.site.id,
                                        "webId": self.web.id,
                                        "listId": "{" + self.ll_list.id + "}",
                                        "uniqueId": guid2,
                                        "width": 352,
                                        "height": 134
                                    }
                                }
                            },
                            "dataVersion": "1.11",
                            "properties": {
                                "id": guid3,
                                "linkUrl": "",
                                "isInlineImage":'true',
                                "siteId": self.site.id,
                                "webId": self.web.id,
                                "listId": "{" + self.ll_list.id + "}",
                                "uniqueId": guid2,
                                "imgHeight": 134,
                                "imgWidth": 352,
                                "imageSourceType": 2,
                                "alignment": "Center",
                                "fixAspectRatio":'false',
                                "overlayText": "",
                                "altText": ""
                            },
                            "containsDynamicDataSource":'false'
                        }
                    })
            canvas_dict.append({
                "controlType": 4,
                "id": "7802ec32-078a-42a7-b455-8eae2538781f",
                "position": {
                    "layoutIndex": 1,
                    "zoneIndex": 1,
                    "sectionIndex": 1,
                    "sectionFactor": 12,
                    "controlIndex": 1
                },
                "addedFromPersistedData":'true',
                "innerHTML": str(content)
            })
            canvas_dict.append({
                "controlType": 0,
                "pageSettingsSlice": {
                    "isDefaultDescription":'true',
                    "isDefaultThumbnail":'true',
                    "isSpellCheckEnabled":'true',
                    "globalRichTextStylingVersion": 0,
                    "rtePageSettings": {
                        "contentVersion": 4
                    }
                }
            })
            return canvas_dict
        except Exception as e:
            self.print_error(f"An error occurred while processing the images: {str(e)}")
            raise

    def fixAttachmentsPath(self, attachments):
        """
        Updates the paths for attachment links and images to ensure they point to the correct location  within the asset folder.

        Parameters:
            attachments (list): A list of BeautifulSoup tags representing the attachments.

        Returns:
            bool: True if the operation was successful.

        Raises:
            Exception: If an unexpected error occurs while processing attachments.
        """
        try:
            main_path = f"{self.ctx._base_url}/{self.assets_folder}"
            for attachment in attachments:
                if attachment.name == 'a':#link
                    attachment['href'] = f"{main_path}/{attachment['href']}"
                elif attachment.name == 'img':
                    attachment['src'] = attachment['href'] = f"{main_path}/{attachment['src']}"                    
            return True
        except Exception as e:
            self.print_error(f"An error occurred while fixing attachment paths: {str(e)}")
            return False
        

    def fixAnchors(self, links, main_content):
        """
        Converts links that reference anchors into corresponding <a> tags with <h3> tags as their text.

        Parameters:
            links (list): A list of BeautifulSoup tags representing the links to process.
            main_content (BeautifulSoup): The main content from which to find corresponding <h3> tags.

        Returns:
            bool: True if the operation was successful.

        Raises:
            Exception: If an unexpected error occurs while processing anchors.
        """
        try:
            for link in links:   
                href = link["href"]           
                if href != "" and href[0] == "#":
                    anchor = main_content.find("h3", {"id":href.replace("#","")})
                    if anchor:
                        anchor.name = "a"
                        soup = BeautifulSoup()
                        h3 = soup.new_tag("h3")
                        h3.string = anchor.text.strip()
                        anchor.string = ""
                        anchor.append(h3)
            return True
        except Exception as e:
            self.print_error(f"An error occurred while fixing attachment paths: {str(e)}")
            raise

    def logLinks(self, links, page_url):
        """
        Logs specified links to a logfile if they contain certain matches.

        Parameters:
            links (list): A list of BeautifulSoup tags representing the links to log.
            page_url (str): The URL of the page being processed.

        Returns:
            bool: True if the operation was successful.

        Raises:
            Exception: If an unexpected error occurs while logging links.
        """
        try:
            LOG_FILENAME = "logfile.log"
            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)
            logging.basicConfig(filename=LOG_FILENAME,level=logging.INFO)
            matches = ["html"]
            for link in links:   
                href = link["href"]           
            if any(match in href for match in matches):
                text = link.text
                log = f"Link: {href}. Text: {text}. URL: {page_url}  "
                logging.info(log)
            return True
        except Exception as e:
            self.print_error(f"An error occurred while logging links: {str(e)}")
            return False
    
    @staticmethod
    def print_error(message):
        """
        Prints an error message in red color.

        Parameters:
        - message (str): The error message to be printed.
        """
        print(f"\033[91m{message}\033[0m")
    
    @staticmethod
    def print_message(message):
        """
        Prints a message in green color.

        Parameters:
        - message (str): The message to be printed.
        """
        print(f"\033[92m{message}\033[0m")

class SetEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        return json.JSONEncoder.default(self, obj)