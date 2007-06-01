# $Id: $
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

import os
import time
import logging
import commands

from time import sleep
from koji import TASK_STATES
from bodhi import buildsys
from bodhi.util import synchronized
from bodhi.exceptions import RepositoryLocked
from threading import Thread, Lock
from turbogears import config
from os.path import exists, join

log = logging.getLogger(__name__)
masher = None
lock = Lock()

class Masher:
    """
    The Masher.  This is a TurboGears extension that runs alongside bodhi that
    is in charge of queueing and dispatching mash composes.
    """
    def __init__(self):
        log.info("Starting the Masher")
        self._queue = []
        self._threads = []
        self.thread_id = 0

    @synchronized(lock)
    def queue(self, updates):
        self._queue.append((self.thread_id, updates))
        self.thread_id += 1
        if len(self._queue) == 1:
            self._mash(self._queue.pop())

    @synchronized(lock)
    def done(self, thread):
        log.debug("Thread %d done!" % thread.id)
        self._threads.remove(thread)
        for update in thread.updates:
            log.debug("Doing post-request stuff for %s" % update.nvr)
            update.request_complete()
        log.info("Push complete!")
        if len(self._queue):
            self._mash(self._queue.pop())

    def _mash(self, task):
        log.debug("Dispatching!")
        thread = MashThread(task[0], task[1])
        self._threads.append(thread)
        thread.start()

class MashThread(Thread):

    def __init__(self, id, updates):
        Thread.__init__(self)
        log.debug("MashThread(%d, %s)" % (id, updates))
        self.id = id
        self.tag = None
        self.updates = updates
        self.koji = buildsys.get_session()
        # which repos do we want to compose? (updates|updates-testing)
        self.repos = set()
        self.success = False
        self.cmd = 'mash -o %s -c ' + config.get('mash_conf') + ' '
        self.actions = []

    def move_builds(self):
        tasks = []
        for update in self.updates:
            release = update.release.name.lower()
            if update.request == 'move':
                self.repos.add('%s-updates' % release)
                self.repos.add('%s-updates-testing' % release)
                self.tag = update.release.dist_tag + '-updates'
            elif update.request == 'push':
                self.repos.add('%s-updates-testing' % release)
                self.tag = update.release.dist_tag + '-updates-testing'
            elif update.request == 'unpush':
                self.tag = update.release.dist_tag + '-updates-candidate'
                if update.status == 'testing':
                    self.repos.add('%s-updates-testing' % release)
                elif update.status == 'stable':
                    self.repos.add('%s-updates' % release)
            current_tag = update.get_build_tag()
            log.debug("Moving %s from %s to %s" % (update.nvr, current_tag,
                                                   self.tag))
            task_id = self.koji.moveBuild(current_tag, self.tag,
                                          update.nvr, force=True)
            self.actions.append((update.nvr, current_tag, self.tag))
            tasks.append(task_id)
        buildsys.wait_for_tasks(tasks)

    def undo_move(self):
        """
        Move the builds back to their original tag
        """
        log.debug("Rolling back updates to their original tag")
        tasks = []
        for action in self.actions:
            log.debug("Moving %s from %s to %s" % (action[0], action[2],
                                                   action[1]))
            task_id = self.koji.moveBuild(action[2], action[1], action[0],
                                          force=True)
            tasks.append(task_id)
        buildsys.wait_for_tasks(tasks)

    def mash(self):
        for repo in self.repos:
            mashdir = join(config.get('mashed_dir'), repo + '-' + \
                           time.strftime("%y%m%d.%H%M"))
            mashcmd = self.cmd % mashdir
            log.info("Running mash on %s" % repo)
            (status, output) = commands.getstatusoutput(mashcmd + repo)
            log.info("status = %s" % status)
            if status == 0:
                self.success = True
                mash_output = '%s/mash.out' % mashdir
                out = file(mash_outpu, 'w')
                out.write(output)
                out.close()
                log.info("Wrote mash output to %s" % mash_output)

                # create a symlink to new repo
                link = join(config.get('mashed_dir'), repo)
                if exists(link):
                    os.unlink(link)
                os.symlink(join(mashdir, repo), link)
            else:
                failed_output = join(config.get('mashed_dir'), 'mash-failed-%s'
                                     % time.strftime("%y%m%d.%H%M"))
                out = file(failed_output, 'w')
                out.write(output)
                out.close()
                log.info("Wrote failed mash output to %s" % failed_output)

    def run(self):
        if self.move_builds():
            self.mash()
            if self.success:
                masher.done(self)
            else:
                log.error("Error mashing.. skipping post-request actions")
                if self.undo_move():
                    log.info("Tag rollback successful!")
                else:
                    log.error("Tag rollback failed!")
        else:
            log.error("Error with build moves.. rolling back")
            self.undo_move()
        log.debug("MashThread done")

def start_extension():
    global masher
    masher = Masher()

def shutdown_extension():
    log.info("Stopping Masher")
    global masher
    del masher
