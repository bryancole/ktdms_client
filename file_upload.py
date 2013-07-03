import itertools
import mimetools
import mimetypes
from cStringIO import StringIO
import urllib
import urllib2
import json

class MultiPartForm(object):
    """Accumulate the data to be used when posting a form."""

    def __init__(self):
        self.form_fields = []
        self.files = []
        self.boundary = mimetools.choose_boundary()
        return
    
    def get_content_type(self):
        return 'multipart/form-data; boundary=%s' % self.boundary

    def add_field(self, name, value):
        """Add a simple field to the form data."""
        self.form_fields.append((name, value))
        return

    def add_file(self, fieldname, filename, fileHandle, mimetype=None):
        """Add a file to be uploaded."""
        body = fileHandle.read()
        if mimetype is None:
            mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        self.files.append((fieldname, filename, mimetype, body))
        return
    
    def __str__(self):
        """Return a string representing the form data, including attached files."""
        # Build a list of lists, each containing "lines" of the
        # request.  Each part is separated by a boundary string.
        # Once the list is built, return a string where each
        # line is separated by '\r\n'.  
        parts = []
        part_boundary = '--' + self.boundary
        
        # Add the form fields
        parts.extend(
            [ part_boundary,
              'Content-Disposition: form-data; name="%s"' % name,
              '',
              value,
            ]
            for name, value in self.form_fields
            )
        
        # Add the files to upload
        parts.extend(
            [ part_boundary,
              'Content-Disposition: file; name="%s"; filename="%s"' % \
                 (field_name, filename),
              'Content-Type: %s' % content_type,
              '',
              body,
            ]
            for field_name, filename, content_type, body in self.files
            )
        
        # Flatten the list and add closing boundary marker,
        # then return CR+LF separated data
        flattened = list(itertools.chain(*parts))
        flattened.append('--' + self.boundary + '--')
        flattened.append('')
        return '\r\n'.join(flattened)

if __name__ == '__main__':
    from SOAPpy import WSDL
    server_base = "http://mercury/knowledgetree"
    #wsdlFile = "http://mercury:8080/ktwebservice/webservice.php?wsdl"
    wsdlFile = server_base + "/ktwebservice/webservice.php?wsdl"
    server = WSDL.Proxy(wsdlFile)
    
    ret = server.login('bryan.cole','clique','')
    session_id = ret.message
    
    # Create the form with simple fields
    form = MultiPartForm()
    form.add_field('session_id', session_id)
    form.add_field('action', 'A')
    form.add_field('output', 'json')
    
    # Add a fake file
    fname = "/home/bryan/checkFile2.py"
    form.add_file('biography2', fname, open(fname))

    # Build the request
    request = urllib2.Request(server_base + '/ktwebservice/upload.php')
    #request.add_header('User-agent', 'PyMOTW (http://www.doughellmann.com/PyMOTW/)')
    body = str(form)
    request.add_header('Content-type', form.get_content_type())
    request.add_header('Content-length', str(len(body)))
    request.add_data(body)

    print
    print 'OUTGOING DATA:'
    print request.get_data()

    print
    print 'SERVER RESPONSE:'
    data_str = urllib2.urlopen(request).read()
    data = json.loads(data_str)
    print data
    print data['upload_status']['biography2']['tmp_name']