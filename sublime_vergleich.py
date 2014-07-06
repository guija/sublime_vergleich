import sublime, sublime_plugin
import difflib
import threading, time, re, ntpath
import re
from pprint import pprint

# List of open / active diffs
diffSessions = []

def getDiffSessionByView(view):
	global diffSessions
	for diff in diffSessions:
		try:
			if view.id() in [diff.leftView.id(), diff.rightView.id()]:
				return diff
		except:
			continue
	return None

def isDiffSessionView(view):
	return getDiffSessionByView(view) != None

# Class that represents a diff session
class DiffSession:

	# Konstruktor
	def __init__(self, leftName, rightName, leftContent, rightContent):

		# init
		self.leftView, self.rightView = None, None
		self.leftRegionBegins, self.rightRegionBegins = [], []
		self.leftRegions, self.rightRegions = [], []
		self.currentRegionIndex = -1
		self.scrollDaemon = None
		self.oldLayout = None

		self.leftContent, self.rightContent = "", ""
		self.leftResult, self.rightResult = "", ""
		self.hunks = []

		self.leftContent = leftContent
		self.rightContent = rightContent
		self.leftName = leftName
		self.rightName = rightName

		global diffSessions
		diffSessions.append(self)

	def diff(self):
		self.leftResult, self.rightResult, self.hunks = doDiff(self.leftContent, self.rightContent)

	def show(self):

		self.setVerticalSplitLayout()

		global diffSessions
		diffNumber = len(diffSessions)

		# create left view
		self.leftView = sublime.active_window().new_file()
		self.leftView.set_scratch(True)
		self.leftView.settings().set('word_wrap', False)
		self.leftView.run_command('fill_with_content', {'content': self.leftResult})
		self.leftView.set_name("Left Diff: " + self.leftName)

		# create right view
		self.rightView = sublime.active_window().new_file()
		self.rightView.set_scratch(True)
		self.rightView.settings().set('word_wrap', False)
		self.rightView.run_command('fill_with_content', {'content': self.rightResult})
		self.rightView.set_name("Right Diff: " + self.rightName)

		# move views to corresponding group
		moveViewToLeft(self.leftView)
		moveViewToRight(self.rightView)

		# create diff regions
		# icon = "dot"
		icon = ""
		leftRegions, rightRegions = [], []
		leftLineRegions, rightLineRegions = [], []
		leftRegionBegins, rightRegionBegins = [], []

		for hunk in self.hunks:

			# left view
			lineBegin, lineEnd =  hunk[0], hunk[1]
			beginLeftPos = self.leftView.text_point(lineBegin, 0)
			endLeftPos = self.leftView.text_point(lineEnd, 0)
			endLineRegion = self.leftView.full_line(endLeftPos)
			endLineContent = self.leftView.substr(endLineRegion)
			endLeftPos += len(endLineContent)
			leftRegion = sublime.Region(beginLeftPos, endLeftPos)
			self.leftRegions.append(leftRegion)
			self.leftRegionBegins.append(beginLeftPos)

			# right view
			lineBegin, lineEnd = hunk[0], hunk[1]
			beginRightPos = self.rightView.text_point(lineBegin, 0)
			endRightPos = self.rightView.text_point(lineEnd, 0)
			endLineRegion = self.rightView.full_line(endRightPos)
			endLineContent = self.rightView.substr(endLineRegion)
			endRightPos += len(endLineContent)
			rightRegion = sublime.Region(beginRightPos, endRightPos)
			self.rightRegions.append(rightRegion)
			self.rightRegionBegins.append(beginRightPos)
		 
		self.leftView.add_regions("VERGLEICH_REGIONS", self.leftRegions, "invalid.deprecated", icon, sublime.DRAW_NO_OUTLINE)
		self.rightView.add_regions("VERGLEICH_REGIONS", self.rightRegions, "invalid.deprecated", icon, sublime.DRAW_NO_OUTLINE)

		if len(self.leftRegionBegins) == 0:
			sublime.error_message("Compared objects are identical")
		else:
			sublime.status_message(str(len(self.leftRegionBegins)) + " Differences detected")

		# init ScrollDaemon
		self.scrollDaemon = ScrollDaemon(self.leftView, self.rightView)
		self.scrollDaemon.start()

	def close(self):

		global diffSessions

		if self.leftView is not None:
			sublime.active_window().focus_view(self.leftView)
			sublime.active_window().run_command('close_file')

		if self.rightView is not None:
			sublime.active_window().focus_view(self.rightView)
			sublime.active_window().run_command('close_file')

		self.leftView, self.rightView = None, None
		self.leftRegions, self.rightRegions = None, None
		self.currentRegionIndex = -1
		self.scrollDaemon.stop()

		if self.oldLayout and len(diffSessions) < 2:
			sublime.active_window().set_layout(self.oldLayout)
			self.oldLayout = None

		try:
			diffSessions.remove(self)
		except:
			pass

	def setVerticalSplitLayout(self):
		# already enough windows.
		if sublime.active_window().num_groups() > 1:
			return
		else:
			# save current layout
			self.oldLayout = sublime.active_window().layout()
			# create split view
			sublime.active_window().set_layout({
			    "cols": [0.0, 0.5, 1.0],
			    "rows": [0.0, 1.0],
			    "cells": [
			        [0, 0, 1, 1],
			        [1, 0, 2, 1]
			    ]
			})

	def highlightCurrentDiff(self, index):

		leftRegion = self.leftRegions[index]
		rightRegion = self.rightRegions[index]

		tmpLeftRegions = []
		for i in range(len(self.leftRegions)):
			if i != index:
				tmpLeftRegions.append(self.leftRegions[i])

		tmpRightRegions = []
		for i in range(len(self.rightRegions)):
			if i != index:
				tmpRightRegions.append(self.rightRegions[i])

		self.leftView.add_regions("VERGLEICH_REGIONS", tmpLeftRegions, "invalid.deprecated", "", sublime.DRAW_NO_OUTLINE)
		self.rightView.add_regions("VERGLEICH_REGIONS", tmpRightRegions, "invalid.deprecated", "", sublime.DRAW_NO_OUTLINE)

		self.leftView.add_regions("VERGLEICH_REGIONS_CURRENT", [leftRegion], "invalid.illegal", "", sublime.DRAW_NO_OUTLINE)
		self.rightView.add_regions("VERGLEICH_REGIONS_CURRENT", [rightRegion], "invalid.illegal", "", sublime.DRAW_NO_OUTLINE)

class VergleichEventListener(sublime_plugin.EventListener):
	def on_close(self, view):

		if isDiffSessionView(view):
			diffSession = getDiffSessionByView(view)

			if None in [diffSession.scrollDaemon, diffSession.leftView, diffSession.rightView]:
				return
			try:
				if view.id() == diffSession.leftView.id():
					diffSession.leftView = None
					diffSession.close()
			except:
				pass

			try:
				if view.id() == diffSession.rightView.id():
					diffSession.rightView = None
					diffSession.close()
			except:
				pass

class ScrollDaemon(threading.Thread):

	leftView, rightView = None, None
	lastLeftViewportPosition, lastRightViewportPosition = (0,0), (0,0)
	waitInMilliseconds = 10.0 / 1000.0

	def __init__(self, leftView, rightView):
		threading.Thread.__init__(self)
		self.leftView = leftView
		self.rightView = rightView

	def run(self):
		while True:

			# one of the windows was closed, stop
			if self.leftView is None or self.rightView is None:
				return

			# handle exception when a view is closed, then 
			# viewport_position will throw an error because
			# the view doesn exist anymore.
			try:
				leftViewportPosition = self.leftView.viewport_position()
				rightViewportPosition = self.rightView.viewport_position()
				if self.lastLeftViewportPosition != leftViewportPosition:
					self.rightView.set_viewport_position(self.leftView.viewport_position(), False)
					self.lastLeftViewportPosition = leftViewportPosition
					self.lastRightViewportPosition = leftViewportPosition
				elif self.lastRightViewportPosition != rightViewportPosition:
					self.leftView.set_viewport_position(self.rightView.viewport_position(), False)
					self.lastLeftViewportPosition = rightViewportPosition
					self.lastRightViewportPosition = rightViewportPosition
			except:
				return
				
			time.sleep(self.waitInMilliseconds)

	def stop(self):
		self.leftView = None
		self.rightView = None

class GotoNextDifferenceCommand(sublime_plugin.TextCommand):
	def run(self, edit):
		if isDiffSessionView(self.view):
			diffSession = getDiffSessionByView(self.view)

			if len(diffSession.leftRegions) == 0:
				sublime.status_message("No difference to go to")
				return

			if diffSession.currentRegionIndex == -1:
				diffSession.currentRegionIndex = 0
			else:
				diffSession.currentRegionIndex = (diffSession.currentRegionIndex+1) % len(diffSession.leftRegions)

			diffSession.highlightCurrentDiff(diffSession.currentRegionIndex)

			if (sublime.active_window().active_view().id() == diffSession.leftView.id() or
				sublime.active_window().active_view().id() == diffSession.rightView.id()):
				sublime.status_message("Difference " + str(diffSession.currentRegionIndex+1) + "/" + str(len(diffSession.leftRegions)))
				diffSession.leftView.show(diffSession.leftRegionBegins[diffSession.currentRegionIndex], True)

class GotoPrevDifferenceCommand(sublime_plugin.TextCommand):
	def run(self, edit):

		if isDiffSessionView(self.view):
			diffSession = getDiffSessionByView(self.view)

			if len(diffSession.leftRegions) == 0:
				sublime.status_message("No difference to go to")
				return

			if diffSession.currentRegionIndex == -1:
				diffSession.currentRegionIndex = len(diffSession.leftRegionBegins)-1
			else:
				diffSession.currentRegionIndex = (diffSession.currentRegionIndex-1) % len(diffSession.leftRegions)

			diffSession.highlightCurrentDiff(diffSession.currentRegionIndex)

			if (sublime.active_window().active_view().id() == diffSession.leftView.id() or
				sublime.active_window().active_view().id() == diffSession.rightView.id()):
				sublime.status_message("Difference " + str(diffSession.currentRegionIndex+1) + "/" + str(len(diffSession.leftRegions)))
				diffSession.leftView.show(diffSession.leftRegionBegins[diffSession.currentRegionIndex], True)

# Dummy command to fill new views
class FillWithContentCommand(sublime_plugin.TextCommand):
	def run(self, edit, content):
		self.view.insert(edit,0,content)

def doDiff(view1Content, view2Content):

	# append new line to contents if they don't end with it so that they end both with a 
	# new line
	if not view1Content.endswith("\n"): view1Content += "\n"
	if not view2Content.endswith("\n"): view2Content += "\n"

	# create arrays of every view content,
	# needed for the diff and for further processing
	# and alignment
	view1ContentList = view1Content.splitlines(True)
	view2ContentList = view2Content.splitlines(True)

	# Do a diff in unified format
	diffResult = list(difflib.unified_diff(view1ContentList, view2ContentList))

	# for debug
	# pprint(diffResult)

	# Begin to analyze the diff at line 2, 
	currentLineIndex = 2

	# contents for the comparision contents
	leftDiffContent, rightDiffContent = "", ""

	# count how many lines are in every diff content
	leftDiffCount, rightDiffCount = 0, 0

	relativeLeftLine, relativeRightLine = 0, 0

	currentDiffHunkBegin = -1
	diffHunks = []

	currentLine = None

	minusCount, plusCount = 0, 0

	while currentLineIndex < len(diffResult):

		# get current line including uniform diff annotation
		currentLine = diffResult[currentLineIndex]
		# get current line content without 
		# uniform diff annotation.
		currentLineContent = currentLine[1:]

		if currentLine.startswith(" "):

			# fill up the side with new lines in which
			# lines are missing.

			if(minusCount > plusCount):
				for i in range(plusCount, minusCount): 
					rightDiffContent += "\n"
					rightDiffCount+=1

			elif(plusCount > minusCount):
				for i in range(minusCount, plusCount):
					leftDiffContent += "\n"
					leftDiffCount+=1

			if currentDiffHunkBegin != -1:
				diffHunks.append((currentDiffHunkBegin, leftDiffCount-1))
				currentDiffHunkBegin = -1

			# reset counters
			minusCount = 0
			plusCount = 0

			# Add line to both sides
			leftDiffContent += currentLineContent
			rightDiffContent += currentLineContent
			relativeLeftLine += 1
			relativeRightLine += 1
			leftDiffCount += 1
			rightDiffCount += 1

		elif currentLine.startswith("-"):	

			# hunk
			if currentDiffHunkBegin == -1:
				currentDiffHunkBegin = leftDiffCount

			# If the side changes, fill not present lines 
			# in the right side on the left side with new lines
			if plusCount > 0:
				for i in range(0, plusCount-1): 
					leftDiffContent += "\n"
					leftDiffCount += 1
				plusCount = 0
			else:
				minusCount+=1
			leftDiffContent += currentLineContent
			leftDiffCount += 1
			relativeLeftLine+=1

		elif currentLine.startswith("+"):

			# hunk
			if currentDiffHunkBegin == -1:
				currentDiffHunkBegin = leftDiffCount

			# If the side changes, fill not present lines 
			# in on the right side with new lines
			if minusCount > 0:
				for i in range(0, minusCount-1): 
					rightDiffContent += "\n"
					rightDiffCount += 1
				minusCount = 0
			else:
				plusCount += 1	
			rightDiffContent += currentLineContent
			relativeRightLine += 1
			rightDiffCount += 1

		elif currentLine.startswith("@@"):
			# TODO: short notation @@ line,line @@
			# long notation
			longNotationRegex = re.match('@@\s-(\d+),(\d+)\s\+(\d+),(\d+)\s@@', currentLine)
			shortNotationRegex = re.match('@@\s-(\d+)\s\+(\d+)\s@@', currentLine)
			shortNotationRegexLeft = re.match('@@\s-(\d+),(\d+)\s\+(\d+)\s@@', currentLine)
			shortNotationRegexRight = re.match('@@\s-(\d+)\s\+(\d+),(\d+)\s@@', currentLine)

			if longNotationRegex:
				# read data for filling up matching content
				diffRegLeftBeginLine = int(longNotationRegex.groups()[0]) - 1
				diffRegLeftLength = int(longNotationRegex.groups()[1])
				diffRegRightBeginLine = int(longNotationRegex.groups()[2]) - 1
				diffRegRightLength = int(longNotationRegex.groups()[3])
			elif shortNotationRegex:
				# read data for filling up matching content
				diffRegLeftBeginLine = int(shortNotationRegex.groups()[0]) - 1
				diffRegLeftLength = 1
				diffRegRightBeginLine = int(shortNotationRegex.groups()[1]) - 1
				diffRegRightLength = 1
			elif shortNotationRegexLeft:
				diffRegLeftBeginLine = int(shortNotationRegexLeft.groups()[0]) - 1
				diffRegLeftLength = int(shortNotationRegexLeft.groups()[1])
				diffRegRightBeginLine = int(shortNotationRegexLeft.groups()[2]) - 1
				diffRegRightLength = 1
			elif shortNotationRegexRight:
				diffRegLeftBeginLine = int(shortNotationRegexRight.groups()[0]) - 1
				diffRegLeftLength = 1
				diffRegRightBeginLine = int(shortNotationRegexRight.groups()[1]) - 1
				diffRegRightLength = int(shortNotationRegexRight.groups()[2])

			if shortNotationRegex or longNotationRegex or shortNotationRegexLeft or shortNotationRegexRight:
				
				# fill up left diffContent
				for i in range(relativeLeftLine, diffRegLeftBeginLine):
					leftDiffContent += view1ContentList[i]
					leftDiffCount += 1
				relativeLeftLine = diffRegLeftBeginLine

				# fill up right diffContent
				for i in range(relativeRightLine, diffRegRightBeginLine):
					rightDiffContent += view2ContentList[i]
					rightDiffCount += 1
				relativeRightLine = diffRegRightBeginLine

				if currentDiffHunkBegin != -1:
					diffHunks.append((currentDiffHunkBegin, leftDiffCount-1))
					currentDiffHunkBegin = -1				

		currentLineIndex+=1

	# do last fill up with new lines
	# fill up with new lines the other side where no content was
	if(minusCount > plusCount):
		for i in range(plusCount, minusCount):
			rightDiffContent += "\n"
			rightDiffCount += 1
	elif(plusCount > minusCount):
		for i in range(minusCount, plusCount):
			leftDiffContent += "\n"
			leftDiffCount += 1

	if currentDiffHunkBegin != -1:
		diffHunks.append((currentDiffHunkBegin, leftDiffCount-1))
		currentDiffHunkBegin = -1

	# is there still content left?
	if(relativeLeftLine < len(view1ContentList)):
		for i in range(relativeLeftLine, len(view1ContentList)):
			leftDiffContent += view1ContentList[i]
			leftDiffCount += 1
	if(relativeRightLine < len(view2ContentList)):
		for i in range(relativeRightLine, len(view2ContentList)):
			rightDiffContent += view2ContentList[i]
			rightDiffCount += 1

	minusCount = 0
	plusCount = 0

	yield leftDiffContent
	yield rightDiffContent
	yield diffHunks

def moveViewToLeft(view):
	# Move left view to left group
	sublime.active_window().focus_group(0)
	sublime.active_window().set_view_index(view, sublime.active_window().active_group(), 0)
	sublime.active_window().focus_view(view)

def moveViewToRight(view):
	# Move right view to right group
	sublime.active_window().focus_group(1)
	sublime.active_window().set_view_index(view, sublime.active_window().active_group(), 0)
	sublime.active_window().focus_view(view)

class CompareToClipboardCommand(sublime_plugin.TextCommand):
	def run(self, edit):

		# get selectioncontent
		selectionContent = ""
		selections = self.view.sel()
		for sel in selections:
			selectionContent += self.view.substr(sel)
			if not selectionContent.endswith("\n"):
				selectionContent += "\n"

		if(selectionContent != ""):
			viewContent = selectionContent
			# todo: fetch appropriate names
			leftName = "(Selection)"
		else:
			viewContent = self.view.substr(sublime.Region(0,self.view.size()))
			# todo: fetch appropriate names
			leftName = ""
		
		# clipboard
		clipboardContent = sublime.get_clipboard()
		if not clipboardContent.endswith("\n"):
			clipboardContent += "\n"
		rightName = "Clipboard"


		leftResult, rightResult, hunks = doDiff(viewContent, clipboardContent)
		showDiff(leftResult, rightResult, hunks)

		diffSession = DiffSession(leftName, rightName, viewContent, clipboardContent)
		diffSession.diff()
		diffSession.show()


class CompareToViewCommand(sublime_plugin.TextCommand):

	menuViewNames, menuViewFileNames, menuViewIds = [], [], []
	view1, view2 = None, None

	# Get a view by its id
	def getViewById(self, id):
		for view in self.view.window().views():
			if view.id() == id:
				return view
		return None

	def loadViews(self):
		# Clear
		self.menuViewNames = []
		self.menuViewFileNames = []
		self.menuViewIds = []
		# get a list of the view for displaying
		# it in the file selection menu
		for view in self.view.window().views():
			if(view.file_name() is None):
				# view contains content that is not saved in a file
				contentPreview = view.substr(sublime.Region(0, min(50, view.size())))
				self.menuViewNames.append([contentPreview , 'untitled'])
			else:
				# get file informations of view
				self.menuViewNames.append([ntpath.basename(view.file_name()), view.file_name()])
			self.menuViewIds.append(view.id())

	def run(self, edit):
		# create list of open views
		self.loadViews()
		self.view1 = sublime.active_window().active_view()
		self.view.window().show_quick_panel(self.menuViewNames, self.menuCallbackView)
		
	def menuCallbackView(self, index):

		if index == -1: return
		viewName = self.menuViewNames[index]
		viewId = self.menuViewIds[index]
		self.view2 = self.getViewById(viewId)
		view1Content = self.view1.substr(sublime.Region(0, self.view1.size()))
		view2Content = self.view2.substr(sublime.Region(0, self.view2.size()))

		selectionLeft = getSelectionString(self.view1)
		selectionRight = getSelectionString(self.view2)

		if(selectionLeft != ""): view1Content = selectionLeft
		if(selectionRight != ""): view2Content = selectionRight

		if not self.view1.file_name():
			leftName = self.view1.substr(sublime.Region(0, min(30, self.view1.size())))
		else:
			leftName = ntpath.basename(self.view1.file_name())

		if not self.view2.file_name():
			rightName = self.view2.substr(sublime.Region(0, min(30, self.view2.size())))
		else:
			rightName = ntpath.basename(self.view2.file_name())

		diffSession = DiffSession(leftName, rightName, view1Content, view2Content)
		diffSession.diff()
		diffSession.show()

class MergeRightCommand(sublime_plugin.TextCommand):
	def run(self, edit):

		if isDiffSessionView(self.view):
			diffSession = getDiffSessionByView(self.view)
			if diffSession.currentRegionIndex == -1:
				# todo error
				print("NOT AT ANY REGION YET, TO TO A DIFF!!")
				return 

			leftRegion = diffSession.leftRegions[diffSession.currentRegionIndex]
			leftRegionContent = diffSession.leftView.substr(leftRegion)
			leftRegionLength = len(leftRegionContent)

			rightRegion = diffSession.rightRegions[diffSession.currentRegionIndex]
			rightRegionContent = diffSession.rightView.substr(rightRegion)
			rightRegionLength = len(rightRegionContent)

			lengthDifference = leftRegionLength - rightRegionLength

			diffSession.rightView.sel().clear()
			diffSession.rightView.sel().add(rightRegion)
			diffSession.rightView.replace(edit, rightRegion, leftRegionContent)
			diffSession.rightView.sel().clear()

			# Adapt all of the regions
			for i in range(len(diffSession.rightRegions)):
				currentRegion = diffSession.rightRegions[i]
				if i == diffSession.currentRegionIndex:
					diffSession.rightRegions[i] = sublime.Region(currentRegion.begin(), currentRegion.end()+lengthDifference)
				if i > diffSession.currentRegionIndex:
					diffSession.rightRegions[i] = sublime.Region(currentRegion.begin()+lengthDifference, currentRegion.end()+lengthDifference)
				else:
					# do nothing, this are the regions before the change
					pass

			diffSession.rightView.add_regions("VERGLEICH_REGIONS", diffSession.rightRegions, "invalid.deprecated", "", sublime.DRAW_NO_OUTLINE)
			diffSession.highlightCurrentDiff(diffSession.currentRegionIndex)

		else:
			# todo error no active session, please activate a diff session 
			return

class MergeLeftCommand(sublime_plugin.TextCommand):
	def run(self, edit):

		if isDiffSessionView(self.view):
			diffSession = getDiffSessionByView(self.view)
			if diffSession.currentRegionIndex == -1:
				# todo error
				print("NOT AT ANY REGION YET, TO TO A DIFF!!")
				return 

			leftRegion = diffSession.leftRegions[diffSession.currentRegionIndex]
			leftRegionContent = diffSession.leftView.substr(leftRegion)
			leftRegionLength = len(leftRegionContent)

			rightRegion = diffSession.rightRegions[diffSession.currentRegionIndex]
			rightRegionContent = diffSession.rightView.substr(rightRegion)
			rightRegionLength = len(rightRegionContent)

			lengthDifference = rightRegionLength - leftRegionLength

			diffSession.leftView.sel().clear()
			diffSession.leftView.sel().add(leftRegion)
			diffSession.leftView.replace(edit, leftRegion, rightRegionContent)
			diffSession.leftView.sel().clear()

			# Adapt all of the regions
			for i in range(len(diffSession.leftRegions)):
				currentRegion = diffSession.leftRegions[i]
				if i == diffSession.currentRegionIndex:
					diffSession.leftRegions[i] = sublime.Region(currentRegion.begin(), currentRegion.end()+lengthDifference)
				if i > diffSession.currentRegionIndex:
					diffSession.leftRegions[i] = sublime.Region(currentRegion.begin()+lengthDifference, currentRegion.end()+lengthDifference)
				else:
					# do nothing, this are the regions before the change
					pass

			diffSession.leftView.add_regions("VERGLEICH_REGIONS", diffSession.leftRegions, "invalid.deprecated", "", sublime.DRAW_NO_OUTLINE)
			diffSession.highlightCurrentDiff(diffSession.currentRegionIndex)

		else:
			# todo error no active session, please activate a diff session 
			return

def getSelectionString(view):
	lines = []
	selections = view.sel()
	for s in selections:
		lines.append(view.substr(s))
	return "\n".join(lines)
