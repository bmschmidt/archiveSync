#! /usr/local/bin/python

import exifread
import datetime
import subprocess
import git
import os
import sys
import time
from bisect import bisect_left
import argparse
import cPickle as pickle

#Also best to have leveldb if you're running it more than once.

#Some local settings:

parser = argparse.ArgumentParser(description="Parser")


### --dry-run prints the changed files to stdout, stores the exif metadata,
### does nothing else.
parser.add_argument('--dry-run', dest='dryRun', action='store_true')
parser.set_defaults(dryRun=False)



#Where the documents are
markdownDirectory = "/Users/bschmidt/Dropbox/gitit/wikidata/"

## Where the photos are on the filesystem,
#specified relative to the markdownDirectory.

photodir = "../static/img/archivalPhotos/"

#What to prefix the thumbnail name in the html: useful for displaying in gitit
photoLinkPrefix = "/img/archivalPhotos/"

#What markdown files inside the repo end in: usually this would be 'md'
pageSuffix = ".page"

#The suffix your camera uses for photos
pictureSuffix = ".JPG"


args = parser.parse_args()
dryRun = args.dryRun


def takeClosest(myList, myNumber):
    """
    Assumes myList is sorted. Returns closest value to myNumber.
    If two numbers are equally close, return the smallest number.
    Taken from http://stackoverflow.com/questions/12141150/from-list-of-integers-get-number-closest-to-a-given-value
    """
    pos = bisect_left(myList, myNumber)
    if pos == 0:
        return myList[0]
    if pos == len(myList):
        return myList[-1]
    before = myList[pos - 1]
    after = myList[pos]
    if after - myNumber < myNumber - before:
       return after
    else:
       return before

   
class GitRepo(object):
    def __init__(self,basedir):
        self.repo = git.repo.base.Repo(markdownDirectory)
        self.commits = dict()
        self.basedir = basedir
        
    def edits(self,pageList):
        self.editList = []
        for markdownPage in pageList:
            self.editList.append(self.repo.blame(self.repo.active_branch,markdownPage))
        return self.editList

class observedDict(object):
    """
    Maintains a database to store exif information for files.

    Mimics dict methods mostly for convenience, but also so you can run
    it once without having leveldb installed.
    """
    def __init__(self,location = "exifCache"):
        import leveldb
        self.dbm = leveldb.LevelDB(location)

    def __getitem__(self,item):
        return self.dbm.Get(item)

    def __setitem__(self,key,value):
        self.dbm.Put(key,value)

    def keys(self):
        return [key for key,value in self.dbm.RangeIter()]

    def resetSeen(self):
        """
        Clear knowledge about what documents have been written to.
        Only for highly arcane script testing stuff.
        """
        keys = self.keys()
        for key in keys:
            tmp = picture(key)
            tmp.document = None
            tmp.Save()
            
class picture(object):
    """
    Stores relevant information about a picture: it's exif tag information,
    time, whether it's already been assigned into a document, etc.

    Includes methods to save into an observedDict class item, so knowledge
    about what's been seen is persistent and you don't have to keep parsing
    the exif information over and over again, which can be time-consuming.
    """
    def __init__(self,string):
        self.filename = os.path.basename(string)
        self.location = string
        self.thumbLocation = self.location + ".thumb.jpg"
        self.document = None
        try:
            self.Load()
        except KeyError:
            print "processing" + string
            self.parseExif()

            
    def parseExif(self):
        """
        Use the cache or parse new exif data.
        """
        file = open(self.location,'rb')
        self.tags = exifread.process_file(file)
        self.time = self.tags['Image DateTime'].printable
        self.time = datetime.datetime.strptime(self.time,"%Y:%m:%d %H:%M:%S")
        self.epoch = time.mktime(self.time.timetuple())
        self.thumbnail = self.tags['JPEGThumbnail']
        self.Save()
        
    def Load(self):
        cached = cache[self.location]
        try:
            tmp_dict = pickle.loads(cached)
            self.__dict__.update(tmp_dict)

        except AttributeError:
            del cached[self.location]

    def Save(self):
        cache[self.location] = pickle.dumps(self.__dict__)
        
    def writeThumbnail(self):
        if not os.path.exists(self.thumbLocation):
            out = open(self.thumbLocation,'wb')
            out.write(self.thumbnail)

    def markdownString(self,label = "An archival photo"):
        #Where the image appears: a link with a thumbnail as a separate line.
        thumbnailSite = photoLinkPrefix + self.filename + ".thumb.jpg"
        fullSizeSite = photoLinkPrefix + self.filename
        return "[![%s](%s)](%s)" % (label,thumbnailSite,fullSizeSite)

    def tagAsIncorporatedIn(self,document):
        self.document = document
        self.Save()
        
cache = observedDict()
#cache.resetSeen()


#Get the files we'll be working with: markdown documents and jpg files, most likely.

photoList = []

for pict in os.listdir(markdownDirectory + photodir):
    if pict.endswith(pictureSuffix):
        if not pict.endswith('.thumb.jpg'):
            try:
                cached = pickle.loads(cache[markdownDirectory + photodir + "/" + pict])
                if cached.document is None:
                    photoList.append(pict)
            except:
                photoList.append(pict)

pageList  = [page for page in os.listdir(markdownDirectory) if page.endswith(pageSuffix)]

pictures = []


#Set up a git repo.
repol = GitRepo(markdownDirectory)

#Get the list of edits associated with that directory.
edits = repol.edits(pageList)

timeLookup = dict()
#Store edits by the second they happened in. Not a real way to store commits. For each second, we'll keep a tuple of document, commit number, and line number that can be used as a key to specify exactly which line. We'll do one for the first line modified by that commit, and one for the last.


editNumber = -1
#First, initialize the list of edits.
for editList in edits:
    editNumber +=1
    commitNumber = -1
    for commit in editList:
        commitNumber +=1
        eTime = commit[0].committed_date
        if eTime not in timeLookup:
            timeLookup[eTime] = dict()
            #The first line is only updated once.
            timeLookup[eTime]['firstLine'] = (editNumber,
                                            commitNumber,
                                            len(commit[1])-1)
        #The last line in the commit gets updated for each subsequent edit
        #If multiple documents are edited in the same commit,
        #behavior is reasonable but undefined. (Probably alphabetical).
        timeLookup[eTime]['lastLine'] = (editNumber,
                                        commitNumber,
                                        len(commit[1])-1)

#Then initialize the photos
for name in photoList:
    try:
        pictures.append(picture(markdownDirectory + photodir + "/" + name))
    except IndexError:
        print "couldn't get full data for " + name + ", skipping"
    except TypeError:
        print "couldn't get full data for " + name + ", skipping"
"""
ChangesToMake is a dict whose keys are a tuple consisting of an editnumber, a commitnumber, and a line number: and whose values are an array of tuples with markdown strings to add and whether they go before or after.
Obviously that's too complicated, and I'm doing something inelegant.
So if the item changesToMake[(3,4,2)] equals [("[a.jpg]()","firstLine"),("[b.jpg]()",lastLine)],
that means the second line of the fourth commit of the third file should have those two links added to it, the first in front and the second behind. (Well, really, the third line of the fifth commit of the fourth file, since we're zero-indexed) 
"""

changesToMake = dict()


#The times of the edits will be matched against the times the pictures are edited:
editTimes = timeLookup.keys()
editTimes.sort()

for myPict in pictures:
    #Write a thumbnail (only done if it doesn't exist)
    myPict.writeThumbnail()
    #find the nearest edit
    nearestEdit = takeClosest(editTimes,myPict.epoch)

    #Should it go near the first or the last element?
    putNear = 'lastLine'
    if myPict.epoch < nearestEdit:
        putNear = 'firstLine'

    if abs(myPict.epoch - nearestEdit) > 60*60*2:
        print "Skipping %s, it's over two hours from the nearest commit" % (markdownDirectory + photodir + myPict.filename)
        myPict.document = "skipping"
        myPict.Save()
        continue

    whereToPlace = timeLookup[nearestEdit][putNear]
    
    if myPict.document is None:
        if not dryRun:
            myPict.tagAsIncorporatedIn(whereToPlace[0])
    else:
        continue
    try:
        changesToMake[whereToPlace] += [(myPict.markdownString(),putNear)]
    except KeyError:
        changesToMake[whereToPlace] = [(myPict.markdownString(),putNear)]

    

"""
finally, loop through the whole diff again, this time writing the files out witheir changes.
"""
        
editNumber = -1
for editList in edits:
    editNumber +=1
    commitNumber = -1
    #We actually open up the file and write it completely anew. Only do this for
    #files which have actually changed, to avoid messing with the timestamps.
    anythingHasChanged = False
    alteredText = []
    for commit in editList:
        commitNumber +=1
        lineNumber = -1
        for line in commit[1]:
            lineNumber+=1
            try:
                picturesToAdd=changesToMake[(editNumber,commitNumber,lineNumber)]
                newLines = [line]
                anythingHasChanged = True
            except:
                #Most of the time, there won't be a change designated for the line.
                alteredText += [line]
                continue
            addBefore = [p[0] for p in picturesToAdd if p[1]=="firstLine"]
            addAfter = [p[0] for p in picturesToAdd if p[1]=="lastLine"]
            #Newline at the end so the last picture doesn't enjamb against the
            #next line. The goal is get one series of photos on the same line,
            #but not do anything too ugly.
            alteredText = alteredText + ["\n"] + addBefore + ["\n",line,"\n"] + addAfter + ["\n"]
            
    if anythingHasChanged:
        if dryRun:
            print "CHANGES TO " + markdownDirectory + "/" + pageList[editNumber] + "\n"*5
            output = sys.stdout
            #output = open("/dev/null","a")
        else:
            output = open(markdownDirectory + "/" + pageList[editNumber],'w')
            
        for line in alteredText:
            output.write(line + "\n")

    
