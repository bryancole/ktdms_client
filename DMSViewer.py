#!/usr/bin/python
from SOAPpy import WSDL
import wx
import threading
import Queue
import urllib
import subprocess
import tempfile
import os, sys
import user
import itertools
import mimetools
import mimetypes
from cStringIO import StringIO
import urllib
import urllib2
import json



search_tooltip = """Valid search fields:
  CheckedOut , 
  CheckedOutBy , 
  CheckedoutDelta , 
  Created , 
  CreatedBy , 
  CreatedDelta , 
  DiscussionText , 
  DocumentId , 
  DocumentText , 
  DocumentType , 
  Filename , 
  Filesize , 
  Folder , 
  FullPath , 
  GeneralText , 
  IntegrationId , 
  IsArchived , 
  IsCheckedOut , 
  IsDeleted , 
  IsImmutable , 
  Metadata , 
  MimeType , 
  Modified , 
  ModifiedBy , 
  ModifiedDelta , 
  Tag , 
  Title , 
  Workflow , 
  WorkflowID , 
  WorkflowState , 
  WorkflowStateID"""


def check(val):
    #print "status", val.status_code, val.message
    pass

def async(func):
    def newfunc(self, *args, **kwds):
        try:
            callback = kwds.pop('callback')
            def newcb(ret):
                wx.CallAfter(callback, ret)
        except KeyError:
            newcb=None
        self.queue.put((func, args, kwds, newcb), block=False)
    return newfunc


def sync(func):
    def newfunc(self, *args, **kwds):
        container = []
        evt = threading.Event()
        def callback(ret):
            container.append(ret)
            evt.set()
        self.queue.put((func, args, kwds, callback), block=False)
        evt.wait(60)
        try:
            return container[0]
        except IndexError:
            raise Exception("async call timeout")
    return newfunc


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
        return '\r\n'.join(str(a) for a in flattened)


AsyncTaskEventId = wx.NewEventType()
EVT_ASYNC_TASK = wx.PyEventBinder(AsyncTaskEventId, 1)


class AsyncTaskEvent(wx.PyEvent):
    def __init__(self, value):
        super(AsyncTaskEvent, self).__init__(AsyncTaskEventId)
        self.working = value
        

class Struct(object):
    def __init__(self, **kwds):
        for k in kwds:
            setattr(self, k, kwds[k])
            

class DMSSession(object):
    #serverName = "http://mercury/knowledgetree"
    serverName = "http://privatekt"
    wsdlFile = "/ktwebservice/webservice.php?wsdl"
    uploadFolder = '/ktwebservice/upload.php'
    def __init__(self, callbacks=[]):
        self.queue = Queue.Queue()
        credentials = os.path.join(user.home, ".dms_credentials.txt")
        if not os.path.exists(credentials):
            wx.MessageBox("No '.dms_credentials.txt' file found in %s"%user.home, style=wx.ICON_ERROR)
            raise Exception("Missing credentials file")
        usern, passwd = open(credentials).read().split("\n")[:2]
        self.username = usern
        self.passwd = passwd
        
        self.callbacks = callbacks
        self._working = False
        
        self.workerThread = threading.Thread(target=self.Worker)
        self.workerThread.setDaemon(True)
        self.workerThread.start()
        
    def close(self):
        self.queue.put(None)
        self.workerThread.join(10.0)
        
    def Worker(self):
        self.server = WSDL.Proxy(self.serverName + self.wsdlFile)
        self.login(self.username, self.passwd)
        while True:
            try:
                item = self.queue.get(block=True, timeout=0.2)
                if item is None:
                    print "Ending worker thread"
                    return
                func, args, kwds, callback = item
                if not self._working:
                    self._working=True
                    for cb in self.callbacks:
                        wx.CallAfter(cb,True)
            except Queue.Empty:
                if self._working:
                    self._working=False
                    for cb in self.callbacks:
                        wx.CallAfter(cb,False)
                continue
            ret = func(self, *args, **kwds)
            if callback is not None:
                callback(ret) 
        
    def login(self, user, passwd):
        ret = self.server.login(str(user),str(passwd),'','')
        check(ret)
        self._id = ret.message
        
    def logout(self):
        ret = self.server.logout(self._id)
        check(ret)
        
    def getFolderDetails(self, folderId):
        pass
    
    @sync
    def downloadDoc(self, docId):
        try:
            ret = self.server.download_document(self._id, int(docId), '')
        except:
            print "Args:", self._id, docId
            raise
        assert ret.status_code==0
        return ret.message
        
    @async
    def getFolderContents(self, folderId):
        ret = self.server.get_folder_contents(self._id, int(folderId),1,'DF')
        check(ret)
        if ret.status_code==22: #permissions error
            return []
        if ret.items is None:
            return []
        return ret.items #[folderItem(a) for a in ret.items]
    
    def _search(self, text, options=""):
        ret = self.server.search(self._id, str(text), options)
        #print "search result", ret
        return ret
    search = async(_search)
    
    def get_clean_uri(self, itemId):
        rsp = self.server.get_clean_uri(self._id, int(itemId))
        return rsp.message
    
    def _upload(self, local_filename, filename):
         # Create the form with simple fields
        form = MultiPartForm()
        form.add_field('session_id', self._id)
        form.add_field('action', 'A')
        form.add_field('output', 'json')
        form.add_file(filename, local_filename, open(local_filename))
    
        # Build the request
        request = urllib2.Request(self.serverName + self.uploadFolder)
        #request.add_header('User-agent', 'PyMOTW (http://www.doughellmann.com/PyMOTW/)')
        body = str(form)
        request.add_header('Content-type', form.get_content_type())
        request.add_header('Content-length', str(len(body)))
        request.add_data(body)
    
#        print
#        print 'OUTGOING DATA:'
#        print request.get_data()
#    
#        print
        result = urllib2.urlopen(request).read()
        data = json.loads(result)
        status = data['upload_status']
        print 'SERVER RESPONSE:', status
        this_fname = status.keys()[0]
        temp_filename = status[this_fname]['tmp_name']
        return temp_filename
    
    @sync
    def delete_document(self, doc_id):
        ret = self.server.delete_document(self._id, 
                                          int(doc_id),
                                          "Because I can...")
        print "delete doc result:", ret
        return ret
    
    @sync
    def delete_folder(self, doc_id):
        ret = self.server.delete_folder(self._id, 
                                          int(doc_id),
                                          "Because I can...")
        print "delete doc result:", ret
        return ret
    
    @async
    def add_document(self, local_filename, folder_id, title="MyDocTitle", 
                     filename=None, documentype="Default"):
        if filename is None:
            filename = os.path.basename(local_filename)
        temp_filename = self._upload(local_filename, filename)
        ret = self.server.add_document(self._id, folder_id, title, filename,
                                 documentype, temp_filename)
        print "add document result:", ret
        return ret
    
    @async
    def add_folder(self, new_folder_name, parent_id):
        ret = self.server.create_folder(self._id, parent_id, new_folder_name)
        print "create folder result:", ret
        return ret
                                 
        

    
        
class NodePopup(wx.Menu):
    def __init__(self, frame, treeid, node):
        self.frame = frame
        self.treeid = treeid
        self.node = node
        wx.Menu.__init__(self)
        id = self.Append(wx.NewId(), "Properties")
        self.Bind(wx.EVT_MENU, self.OnProperties, id)
        id = self.Append(wx.NewId(), "Copy URL")
        self.Bind(wx.EVT_MENU, self.OnCopyURL, id)
        
    def OnProperties(self, event):
        dlg = PropertiesDialog(self.frame, self.node)
        dlg.ShowModal()
        
    def OnCopyURL(self, event):
        session = self.frame.session
        self.node.CopyURLToClipboard(session)
        
        
class FolderPopup(NodePopup):
    def __init__(self, frame, treeid, node):
        super(self.__class__, self).__init__(frame, treeid, node)
        id = self.Append(wx.NewId(), "Refresh")
        self.Bind(wx.EVT_MENU, self.OnRefresh, id)
        id = self.Append(wx.NewId(), "Add Document")
        self.Bind(wx.EVT_MENU, self.OnUpload, id)
        id = self.Append(wx.NewId(), "Add Folder")
        self.Bind(wx.EVT_MENU, self.OnAddFolder, id)
        self.Append(wx.NewId(), "Rename")
        id = self.Append(wx.NewId(), "Delete")
        self.Bind(wx.EVT_MENU, self.OnDelete, id)
        
    def OnAddFolder(self, event):
        name = wx.GetTextFromUser("Please enter name for new folder", "Create folder...", "New Folder")
        if name:
            self.node.AddFolder(name, self.frame.session)
            self.frame.RefreshNode(self.treeid, recursive=False)
        
    def OnUpload(self, event):
        fname = wx.FileSelector("Choose file to upload")
        if os.path.exists(fname) and os.path.isfile(fname):
            title = wx.GetTextFromUser("Please enter document title", "Enter Document Title", "MyDocTitle")
            if title:
                self.node.UploadDoc(fname, self.frame.session, title=title)
                self.frame.RefreshNode(self.treeid, recursive=False)
            
    def OnRefresh(self, event):
        self.frame.RefreshNode(self.treeid, recursive=False)
            
    def OnDelete(self, event):
        title = self.node._properties['title']
        if wx.MessageBox('Delete folder "%s"?'%title,
                         style=wx.YES_NO)==wx.YES:
            self.node.Delete(self.frame.session)
    
        
class DocumentPopup(NodePopup):
    _openFiles=[]
    def __init__(self, frame, treeid, node):
        super(self.__class__, self).__init__(frame, treeid, node)
        
        id = self.Append(wx.NewId(), "Open")
        self.Bind(wx.EVT_MENU, self.OnOpen, id)
        
        id = self.Append(wx.NewId(), "Download")
        self.Bind(wx.EVT_MENU, self.OnDownload, id)
        
        self.Append(wx.NewId(), "Check Out")
        item = self.Append(wx.NewId(), "Check In")
        item.Enable(False)
        self.Append(wx.NewId(), "Copy")
        self.Append(wx.NewId(), "Rename")
        id = self.Append(wx.NewId(), "Delete")
        self.Bind(wx.EVT_MENU, self.OnDelete, id)
        
    def OnDelete(self, event):
        if wx.MessageBox("Do you really want to delete this file?",
                         style=wx.YES_NO)==wx.YES:
            self.node.Delete(self.frame.session)
        
    def OnDownload(self, event):
        msg, filename = self.node.DownloadDoc(self.frame.session)
        fname = wx.FileSelector("Save to file...", 
                                default_filename=filename,
                                flags=wx.SAVE)
        if fname:
            url = msg #self.frame.session.serverName + msg
            urllib.urlretrieve(url, fname)
            
    def OnOpen(self, event):
        msg, filename = self.node.DownloadDoc(self.frame.session)
        ext = os.path.splitext(filename)[1]
        fobj = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        url = msg #self.frame.session.serverName + msg
        print "fetching url:", url
        urllib.urlretrieve(url, fobj.name)
        fobj.close()
        if sys.platform.startswith("win"):
            os.startfile(fobj.name)
        else:
            launch = {'win32':fobj.name, 'linux2':["gnome-open", fobj.name]}
            print "launched program", fobj.name
            subprocess.Popen(launch[sys.platform])
        print "launched program", fobj.name
        self._openFiles.append(fobj)
        
        
class PropertiesDialog(wx.Dialog):
    hide = ['treeid','mime_display','storage_path',
            'items','item_type','mime_icon_path']
    def __init__(self, parent, node):
        wx.Dialog.__init__(self, parent,-1,"Properties...", 
                           size=(500,400), style=wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)
        subwin = wx.ScrolledWindow(self, -1)
        sizer = wx.BoxSizer(wx.VERTICAL)
        keys = (k for k in node.__dict__ if not k.startswith('_'))
        keys = (k for k in keys if k not in self.hide)
        for k in keys:
            val = getattr(node, k)
            text = "%s : %s"%(k, str(val))
            label = wx.StaticText(subwin, -1, text)
            sizer.Add(label, 0, wx.ALL, 5)
        subwin.SetSizer(sizer)
        #self.Fit()
        subwin.SetScrollRate(20,20)
        self.Bind(wx.EVT_CLOSE, self.OnClose)
    
    def OnClose(self, event):
        self.Destroy()
        
        
class ModelNode(object):
    def __init__(self, soapItems):
        d = soapItems.__dict__
        items = (k for k in d if not k.startswith('_'))
        properties = {}
        for k in items:
            properties[k] = d[k]
            setattr(self, k, d[k])
        self._properties = properties
        
    def CopyURLToClipboard(self, session):
        try:
            URI = self._properties['clean_uri']
        except KeyError:
            URI = session.get_clean_uri(self.id)
        base_url = session.serverName
        
        clipdata = wx.TextDataObject()
        clipdata.SetText(base_url + URI)
        wx.TheClipboard.Open()
        wx.TheClipboard.SetData(clipdata)
        wx.TheClipboard.Close()
            
    def GetPopupMenu(self, frame, treeid, node):
        return self._popup(frame, treeid, node)
    
    def Drop(self, session, data):
        pass
    
    
class DummyNode(object):
    def __init__(self, id):
        self.id = id
    
        
class Folder(ModelNode):    
    _popup = FolderPopup
    def GetChildren(self, session, callback):
        session.getFolderContents(self.id, callback=callback)
        
    def Drop(self, session, data):
        pass
    
    def UploadDoc(self, fname, session, title=""):
        ret = session.add_document(fname, self.id, title=title)
        return ret
    
    def AddFolder(self, new_folder_name, session):
        ret = session.add_folder(new_folder_name, self.id)
        
    def Delete(self, session):
        ret = session.delete_folder(self.id)

    
class Document(ModelNode):
    _popup = DocumentPopup
    def DownloadDoc(self, session):
        ret = session.downloadDoc(self.id)
        return ret, self.filename
    
    def Delete(self, session):
        ret = session.delete_document(self.id)


class SearchView(wx.Panel):
    def __init__(self, parent, session, imList):
        wx.Panel.__init__(self, parent, -1)
        
        self.session = session
        
        self.search_ctrl = wx.SearchCtrl(self, size=(200,-1), style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetToolTipString(search_tooltip)
        
        style=wx.TR_HIDE_ROOT
        self.tree = wx.TreeCtrl(self, -1, style=style)
        self.tree.AssignImageList(imList)
        self.imList = imList
        
        sizer =wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.search_ctrl, 0, wx.ALL|wx.EXPAND, 2)
        sizer.Add(self.tree, 1, wx.ALL|wx.EXPAND, 2)
        
        self.SetSizer(sizer)
        
        self.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self.OnSearch, self.search_ctrl)
        self.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, self.OnCancel, self.search_ctrl)
        self.Bind(wx.EVT_TEXT_ENTER, self.OnDoSearch, self.search_ctrl)
        
        self.tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self.OnRClick)
        self.tree.Bind(wx.EVT_TREE_ITEM_GETTOOLTIP, self.OnToolTip)
        
        self.search_results = []

    def OnSearch(self, event):
        self.OnDoSearch(event)
    
    def OnCancel(self, event):
        pass
    
    def OnDoSearch(self, event):
        text = self.search_ctrl.GetValue()
        def callback(search_result):
            code = search_result.status_code
            msg = search_result.message
            hits = search_result.hits
            if code != 0:
                err = "Error code: %d\n%s"%(code, msg)
                dlg = wx.MessageDialog(self, err, "Search Error")
                dlg.ShowModal()
            else:
                self.show_results(hits)
        self.session.search(text, callback=callback)
        
    def show_results(self, hits):
        self.tree.DeleteAllItems()
        if not hits:
            return
        self.search_results = []
        rootid = self.tree.AddRoot("Results:")
        self.tree.SetItemHasChildren(rootid)
        for hit in hits:
            doc = Document(hit)
            treeid = self.tree.AppendItem(rootid, doc.filename, 
                                          data=wx.TreeItemData(doc),
                                          image=self.imList.fileidx)
            doc.treeid = treeid
            doc.id = doc.document_id
            self.search_results.append(doc)
            
    def OnRClick(self, event):
        treeid = event.GetItem()
        node = self.tree.GetItemData(treeid).GetData()
        menu = node.GetPopupMenu(self, treeid, node)
        self.tree.PopupMenu(menu, event.GetPoint())
        
    def OnWorking(self, value):
        if value:
            self.tree.SetCursor(WaitCursor)
        else:
            self.tree.SetCursor(DefaultCursor)
            
    def OnToolTip(self, event):
        treeid = event.GetItem()
        node = self.tree.GetItemData(treeid).GetData()
        if treeid.IsOk():
            get_props = ("%s : %s"%(k,str(v)) for k,v in node._properties.items() if v != "n/a")
            properties = "\n".join(get_props)
            event.SetToolTip(properties)
        else:
            event.SetToolTip('No item')
    
    
class TreeDropTarget(wx.FileDropTarget):
    def __init__(self, tree, session):
        wx.FileDropTarget.__init__(self)
        self.tree = tree
        self.session = session
        
    def OnDropFiles(self, x,y, data):
        tree = self.tree
        print x,y,data
        treeid, flags = tree.HitTest(wx.Point(x,y))
        print treeid, flags
        obj = tree.GetPyData(treeid)
        obj.Drop(self.session, data)
    
        
class TreeView(wx.Panel):
    _shift_down = False
    
    def __init__(self, parent, session, imList):
        wx.Panel.__init__(self, parent, -1)
        
        self.session = session
        
        style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT 
        self.tree = wx.TreeCtrl(self, -1, style=style)
        self.tree.AssignImageList(imList)
        self.fldridx = imList.fldridx
        self.fldropenidx = imList.fldropenidx
        self.fileidx     = imList.fileidx
        
        self._drop_target = TreeDropTarget(self.tree, session)
        self.tree.SetDropTarget(self._drop_target)
        
        rootFolder = Folder(Struct(id=1))
        rootid = self.tree.AddRoot("folders", data=wx.TreeItemData(rootFolder), image=self.fldridx)
        rootFolder.treeid = rootid
        self.tree.SetItemHasChildren(rootid)
        dummy = DummyNode(wx.NewId())
        dummy_id = self.tree.AppendItem(rootid, "...fetching data...", 
                         data=wx.TreeItemData(dummy))
        dummy.treeid = dummy_id
        
        self.tree.Bind(wx.EVT_TREE_ITEM_EXPANDED, self.OnExpandItem)
        self.tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self.OnRClick)
        self.tree.Bind(wx.EVT_TREE_ITEM_GETTOOLTIP, self.OnToolTip)
        self.tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.OnExpandItem)
        self.tree.Bind(wx.EVT_LEFT_DOWN, self.OnClick)
        self.tree.Bind(wx.EVT_LEFT_UP, self.OnClick)
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.tree, 1, wx.ALL|wx.EXPAND, 2)
        self.SetSizer(sizer)
        
    def OnActivate(self, evt):
        print evt
        
    def IterChildren(self, treeid):
        child = self.tree.GetFirstChild(treeid)
        while child[0].IsOk():
            yield child[0]
            child = self.tree.GetNextChild(treeid, child[1])
            
    def makeSyncCallback(self, treeid, childNodes, recursive=False):
        currentMap = dict((child.id, child) for child in childNodes)
        currentIds = set(currentMap)
        def callback(itemList):
            serverMap = dict((item.id, item) for item in itemList)
            serverIds = set(serverMap)
            items = sorted((serverMap[id] for id in serverIds.difference(currentIds)),
                           key=lambda x:(x.item_type, x.filename))
            for item in items:
                if item.item_type == 'F':
                    node = Folder(item)
                    img = self.fldridx
                else:
                    img = self.fileidx
                    node = Document(item)
                newid = self.tree.AppendItem(treeid, item.filename, 
                                        data=wx.TreeItemData(node), image=img)
                print "Appended", newid
                node.treeid = newid
                if item.item_type == 'F':
                    self.tree.SetItemHasChildren(newid, True)
                    if recursive:
                        print "recursing...", node.title
                        self.tree.Expand(newid)
                        callback = self.makeSyncCallback(newid, [], recursive)
                        node.GetChildren(self.session, callback)
                    else:
                        dummy = DummyNode(wx.NewId())
                        dummy_id = self.tree.AppendItem(newid, "...fetching data...", 
                                         data=wx.TreeItemData(dummy))
                        dummy.treeid = dummy_id
            for id in currentIds.difference(serverIds):
                node = currentMap[id]
                self.tree.Delete(node.treeid)
            
        return callback
        
    def OnExpandItem(self, event):
        print "expanding", event
        recursive = self._shift_down
        treeid = event.GetItem()
        self.RefreshNode(treeid, recursive)
        
    def RefreshNode(self, treeid, recursive=False):
        folder = self.tree.GetItemData(treeid).GetData()
        children = [self.tree.GetItemData(id).GetData() for id in self.IterChildren(treeid)]
        callback = self.makeSyncCallback(treeid, children, recursive)
        folder.GetChildren(self.session, callback)
        
    def OnRClick(self, event):
        treeid = event.GetItem()
        node = self.tree.GetItemData(treeid).GetData()
        menu = node.GetPopupMenu(self, treeid, node)
        self.tree.PopupMenu(menu, event.GetPoint())
        
    def OnToolTip(self, event):
        treeid = event.GetItem()
        node = self.tree.GetItemData(treeid).GetData()
        if isinstance(node, DummyNode):
            return
        if treeid.IsOk():
            get_props = ("%s : %s"%(k,str(v)) for k,v in node._properties.items() if v != "n/a")
            properties = "\n".join(get_props)
            event.SetToolTip(properties)
        else:
            event.SetToolTip('No item')
            
    def OnClick(self, event):
        self._shift_down = event.ShiftDown()
        event.Skip()
        
    def OnWorking(self, value):
        if value:
            self.tree.SetCursor(WaitCursor)
        else:
            self.tree.SetCursor(DefaultCursor)
        
        
class DMSViewerApp(wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self, None, -1, "DMS View", size=(500,800))
        self.Bind(wx.EVT_CLOSE, self.OnClose)
        
        mb = wx.MenuBar()
        bookmarks = wx.Menu()
        
        isz = (16,16)
        il = wx.ImageList(isz[0], isz[1])
        il.fldridx     = il.Add(wx.ArtProvider_GetBitmap(wx.ART_FOLDER,      wx.ART_OTHER, isz))
        il.fldropenidx = il.Add(wx.ArtProvider_GetBitmap(wx.ART_FILE_OPEN,   wx.ART_OTHER, isz))
        il.fileidx     = il.Add(wx.ArtProvider_GetBitmap(wx.ART_NORMAL_FILE, wx.ART_OTHER, isz))
        
        mb.Append(bookmarks, "Bookmarks")
        self.SetMenuBar(mb)
        
        self.session = DMSSession([self.OnWorking])
        
        self.notebook = wx.Notebook(self, -1)
        
        self.tree_view = TreeView(self.notebook, self.session, il)
        self.search_view = SearchView(self.notebook, self.session, il)
        
        self.notebook.AddPage(self.tree_view, "Browse Documents")
        self.notebook.AddPage(self.search_view, "Search")
        
    def OnClose(self, event):
        print "closing"
        self.session.close()
        self.Destroy()
        
    def OnWorking(self, value):
        self.tree_view.OnWorking(value)
        self.search_view.OnWorking(value)
            
if __name__=="__main__":
    app = wx.App(0)
    DefaultCursor = wx.StockCursor(wx.CURSOR_DEFAULT)
    WaitCursor = wx.StockCursor(wx.CURSOR_WAIT)
    frame = DMSViewerApp()
    frame.Show()
    app.MainLoop()
    print "EXIT"
    time.sleep(1.0)
