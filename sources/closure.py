import xml.etree.ElementTree as ET
import tempfile
import os
import re

class evaluation:

	def __init__(self, document_id, xml_folder, dev=True): 

		self.events = {}
		self.timex3 = {}
		self.document_id = document_id
		self.dev = dev
		self.xml_folder = xml_folder

	def eval(self, labels, event_ids, sen_ids, preds):

		# read the corresponding xml file without tlinks
		xml_file = os.path.join(self.xml_folder, str(self.document_id)+'.xml')
		text=open(xml_file).read()
		text=re.sub(u"[\x00-\x08\x0b-\x0c\x0e-\x1f]+",u"",text)
		text=re.sub('&', ' ', text)
		root = ET.fromstring(text)
		self.parseTags(root[1])

		xmlfile = open(os.path.join(self.xml_folder, str(self.document_id)+'.xml'), 'r')
		lines = xmlfile.readlines()
		writefile = open(os.path.join(self.xml_folder, str(self.document_id)+'.xml'), 'w')
		for line in lines:
			if "<TLINK" in line: continue
			elif "</TAGS>" not in line:
				writefile.write(line)
			else:
				for i,([id1, id2], label, sen_id, pred) in enumerate(zip(event_ids, labels, sen_ids, preds)):

					event1 = (self.events[id1] if "E" in id1 else self.timex3[id1]).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')
					event2 = (self.events[id2] if "E" in id2 else self.timex3[id2]).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')

					writefile.write('<TLINK id="TL{}" fromID="{}" fromText="{}" toID="{}" toText="{}" type="{}" senid="{}" pred="{}" />'.format(str(i+1), id1, event1, id2, event2, label.upper(), sen_id[1], pred) + '\n')
				writefile.write(line)
		writefile.close()
		

	def parseTags(self, tags):

		for child in tags:
			if child.tag == 'EVENT':
				self.events[child.attrib['id']] = child.attrib['text']  

			elif child.tag == 'TIMEX3':
				self.timex3[child.attrib['id']] = child.attrib['text'] 


