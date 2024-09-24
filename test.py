from os import getcwd
#from office365.sharepoint.fields.field_multi_choice_value import FieldMultiChoiceValue
from confluenc_to_sharepoint.confluenc_to_sharepoint import ConfluencToSharePoint

#init class and load it with settings file
importer = ConfluencToSharePoint(f"{getcwd()}/settings.cfg")
html_files_path = f"{getcwd()}\\..\\5570580dfd4e8f281a4cc683cf9630c6d3cfaf\\"

#if there is SP fields to be updated
sp_fields = {
    #"My_Page_Type" : "TESTPAGE2",
    #"Label" : FieldMultiChoiceValue(["Label Text"]),
}
#remove unnecessary html emelents from the exported HTML
elements_to_remove = ["rw_corners","wysiwyg-unknown-macro"]
result = importer.parse_confluence_HTML(html_files_path, sp_fields, elements_to_remove)
#print(result)