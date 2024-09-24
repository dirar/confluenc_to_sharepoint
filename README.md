# confluenc_to_sharepoint

confluenc_to_sharepoint is a Python library for importing HTML file exported from Confluenc Wiki

## Installation

Use the package manager [pip](https://pip.pypa.io/en/stable/) to install confluenc_to_sharepoint.

```bash
pip install -r requirements.txt
```

```python
## Usage
#init class and load settings file
importer = ConfluencToSharePoint(f"{getcwd()}/settings.cfg")
#Path for the exported HTML folder 
html_files_path = f"{getcwd()}\\..\\5570580dfd4e8f281a4cc683cf9630c6d3cfaf\\"
#if there is SP fields to be updated
sp_fields = {
    #"My_Page_Type" : "TESTPAGE2",
    #"Label" : FieldMultiChoiceValue(["Label Text"]),
}
#remove unnecessary html emelents from the exported HTML
elements_to_remove = ["rw_corners","wysiwyg-unknown-macro"]
result = importer.parse_confluence_HTML(html_files_path, sp_fields, elements_to_remove)
```

## Contributing

Pull requests are welcome. For major changes, please open an issue first
to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License

[MIT](https://choosealicense.com/licenses/mit/)