# This is an extension plugin  for minqlx.
# Copyright (C) 2016 mattiZed (github) aka mattiZed (ql)
# Copyright (C) 2016 Melodeiro (github)

# You can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation,
# either version 3 of the License, or (at your option) any later version.

# You should have received a copy of the GNU General Public License
# along with minqlx. If not, see <http://www.gnu.org/licenses/>.

# This is a queue plugin written for Mino's Quake Live Server Mod minqlx.
# Some parts of it were inspired by the original queueinfo plugin which was
# written by WalkerX (github) for the old minqlbot.

# The plugin put players to the queue when teams are full or even if match in progress.
# When more players adding or there is the place for someone, guys from queue putting to the game.

# The plugin also features an AFK list, to which players can
# subscribe/unsubscribe to.

# Its the alpha state, so any bugs might happen

# For correctly updating the player tags after using !clan, server needs changed clan.py:
# https://github.com/Melodeiro/minqlx-plugins_MinoMino/blob/master/clan.py
# Also you can use the updated version of uneventeams.py, which will put players in queue:
# https://github.com/Melodeiro/minqlx-plugins_mattiZed/blob/master/uneventeams.py

import minqlx
import time
import threading

TEAM_BASED_GAMETYPES = ("ca", "ctf", "dom", "ft", "tdm", "ad", "1f", "har")
NONTEAM_BASED_GAMETYPES = ("ffa", "race", "rr")
_tag_key = "minqlx:players:{}:clantag"


class queue(minqlx.Plugin):
    def __init__(self):
        self.add_hook("new_game", self.handle_new_game)
        self.add_hook("game_end", self.handle_game_end)
        self.add_hook("player_loaded", self.handle_player_loaded)
        self.add_hook("player_disconnect", self.handle_player_disconnect)
        self.add_hook("team_switch", self.handle_team_switch)
        self.add_hook("team_switch_attempt", self.handle_team_switch_attempt)
        self.add_hook("set_configstring", self.handle_config_string, priority=minqlx.PRI_HIGH)
        self.add_hook("client_command", self.handle_client_command)
        self.add_hook("vote_ended", self.handle_vote_ended)
        self.add_hook("console_print", self.handle_console_print)
        self.add_command(("q", "queue"), self.cmd_show_queue)
        self.add_command("afk", self.cmd_afk)
        self.add_command("here", self.cmd_playing)
        self.add_command("qversion", self.cmd_queue_version)
        self.add_command(("teamsize", "ts"), self.cmd_team_size, priority=minqlx.PRI_HIGH)

        # Commands for debugging
        self.add_command("qpush", self.cmd_queue_push, 5)
        self.add_command("qadd", self.cmd_queue_add, 5, usage="<id>")
        self.add_command("qupd", self.cmd_queue_update, 5)

        self.version = "2.7.3"
        self.plugin_updater_url = "https://raw.githubusercontent.com/Melodeiro/minqlx-plugins_mattiZed/master/queue.py"
        self._queue = []
        self._afk = []
        self._tags = {}
        self.initialize()
        self.is_red_locked = False
        self.is_blue_locked = False
        self.is_push_pending = False
        self.is_end_screen = self.game is None  # game is None is between game_end (probably) and new_game
        self.set_cvar_once("qlx_queueSetAfkPermission", "2")
        self.set_cvar_once("qlx_queueAFKTag", "^3AFK")

        self.test_logger = minqlx.get_logger()

    def initialize(self):
        for p in self.players():
            self.update_tag(p)
        self.unlock()

    def handle_new_game(self):
        self.is_end_screen = False
        self.is_red_locked = False
        self.is_blue_locked = False

        if self.game.type_short not in TEAM_BASED_GAMETYPES + NONTEAM_BASED_GAMETYPES:
            self._queue = []
            for p in self.players():
                self.update_tag(p)
        else:
            self.take_from_queue(1)

    def handle_game_end(self, data):
        self.is_end_screen = True

    @minqlx.thread
    def add_to_queue(self, player, pos=-1):
        """Safely adds players to the queue"""
        if player not in self._queue:
            if pos == -1:
                self._queue.append(player)
            else:
                self._queue.insert(pos, player)
                for p in self._queue:
                    self.update_tag(p)
            for p in self.teams()['spectator']:
                self.center_print(p, "{} joined the Queue".format(player.name))
        if player in self._queue:
            self.center_print(player, "You are in the queue to play")
        self.update_tag(player)
        self.take_from_queue()

    def remove_from_queue(self, player, update=True):
        """Safely removes player from the queue"""
        if player in self._queue:
            self._queue.remove(player)
        for p in self._queue:
            self.update_tag(p)
        if update:
            self.update_tag(player)

    @minqlx.thread
    def take_from_queue(self, delay: float = 0):
        """Check if there is the place and players in queue, and put them in the game"""
        if self.is_push_pending:
            return

        self.is_push_pending = True
        time.sleep(delay)
        self.is_push_pending = False

        if len(self._queue) == 0:
            return
        if self.is_end_screen:
            return
        if self.game.state not in ['in_progress', 'warmup']:
            return

        self.check_for_place()

    @minqlx.next_frame
    def check_for_place(self):
        if self.is_end_screen:
            return
        max_players = self.get_max_players()
        teams = self.teams()
        red_amount = len(teams["red"])
        blue_amount = len(teams["blue"])

        if self.game.type_short in TEAM_BASED_GAMETYPES:
            diff = red_amount - blue_amount
            if diff > 0 and not self.is_blue_locked:
                self.push_to_team(diff, "blue")
            elif diff < 0 and not self.is_red_locked:
                self.push_to_team(-diff, "red")
            elif red_amount + blue_amount < max_players:
                if len(self._queue) > 1 and not self.is_blue_locked and not self.is_red_locked:
                    self.push_to_both()  # add elo here for those, who want
                elif self.game.state == 'warmup':  # for the case if there is 1 player in queue
                    if not self.is_red_locked and red_amount < int(self.game.teamsize):
                        self.push_to_team(1, "red")
                    elif not self.is_blue_locked and blue_amount < int(self.game.teamsize):
                        self.push_to_team(1, "blue")

        # who cares about ffa?
        elif self.game.type_short in NONTEAM_BASED_GAMETYPES:
            if len(self.teams()["free"]) < max_players:
                self.push_to_team(max_players - len(self.teams()["free"]), "free")

    @minqlx.next_frame
    def push_to_team(self, amount, team):
        """Safely put certain amount of players to the selected team"""
        if not self.is_end_screen:
            for count, player in enumerate(self._queue, start=1):
                if player in self.teams()['spectator'] and player.connection_state == 'active':
                    self._queue.pop(0).put(team)
                elif player.connection_state not in ['connected', 'primed']:
                    self.remove_from_queue(player)
                if count == amount:
                    self.take_from_queue(0.5)
                    return

    @minqlx.next_frame
    def push_to_both(self):
        if len(self._queue) > 1 and not self.is_end_screen:
            spectators = self.teams()['spectator']
            if self._queue[0] in spectators and self._queue[0].connection_state == 'active':
                if self._queue[1] in spectators and self._queue[1].connection_state == 'active':
                    # self.test_logger.warning("pop out {}".format(self._queue[0]))
                    self._queue.pop(0).put("red")
                    # self.test_logger.warning("pop out {}".format(self._queue[0]))
                    self._queue.pop(0).put("blue")
                elif self._queue[1].connection_state not in ['connected', 'primed']:
                    self.remove_from_queue(self._queue[1])
            elif self._queue[0].connection_state not in ['connected', 'primed']:
                self.remove_from_queue(self._queue[0])
            self.take_from_queue(0.5)

    @minqlx.thread
    def remove_afk(self, player, update=True):
        """Safely removes players from afk list"""
        if player in self._afk:
            self._afk.remove(player)
            if update:
                self.update_tag(player)

    def get_position_in_queue(self, player):
        """Returns position of the player in queue"""
        try:
            return self._queue.index(player)
        except ValueError:
            return -1

    def set_afk(self, player):
        """Returns True if player's state could be set to AFK"""
        if player in self.teams()['spectator'] and player not in self._afk:
            self._afk.append(player)
            self.remove_from_queue(player)
            return True
        return False

    @minqlx.thread
    def remove_tag(self, player):
        if player.steam_id in self._tags:
            del self._tags[player.steam_id]

    def update_tag(self, player):
        """Update the tags dictionary and start the set_configstring event for tag to apply"""

        @minqlx.next_frame
        def update():
            if player in self.players():
                player.clan = player.clan

        if player in self.players():
            addition = ""
            position = self.get_position_in_queue(player)

            if position > -1:
                addition = '({})'.format(position + 1)
            elif player in self._afk:
                addition = '({})'.format(self.get_cvar("qlx_queueAFKTag"))
            elif self.game is not None and self.game.type_short not in TEAM_BASED_GAMETYPES + NONTEAM_BASED_GAMETYPES:
                addition = ""
            elif player in self.teams()['spectator']:
                addition = '(s)'

            self._tags[player.steam_id] = addition

            update()

    @minqlx.next_frame
    def center_print(self, player, message):
        if player in self.players():
            minqlx.send_server_command(player.id, "cp \"{}\"".format(message))

    def get_max_players(self):
        max_players = int(self.game.teamsize)
        if self.game.type_short in TEAM_BASED_GAMETYPES:
            max_players = max_players * 2
        if max_players == 0:
            max_players = self.get_cvar("sv_maxClients", int)
        return max_players

    # Plugin Handles and Commands
    def handle_player_disconnect(self, player, reason):
        self.remove_afk(player, False)
        self.remove_from_queue(player, False)
        self.remove_tag(player)
        self.take_from_queue(0.5)

    def handle_player_loaded(self, player):
        self.update_tag(player)

    def handle_team_switch(self, player, old_team, new_team):
        if new_team != "spectator":
            self.remove_from_queue(player)
            self.remove_afk(player)
        else:
            self.update_tag(player)
            self.take_from_queue(0.5)

    def handle_team_switch_attempt(self, player, old_team, new_team):
        if self.is_end_screen or self.game.type_short not in TEAM_BASED_GAMETYPES + NONTEAM_BASED_GAMETYPES:
            return

        if new_team != "spectator" and old_team == "spectator":
            teams = self.teams()
            max_players = self.get_max_players()
            if len(teams["red"]) + len(teams["blue"]) == max_players \
                    or len(teams["free"]) == max_players \
                    or self.game.state == 'in_progress' \
                    or len(self._queue) > 0 \
                    or self.is_red_locked \
                    or self.is_blue_locked:
                self.remove_afk(player)
                self.add_to_queue(player)
                return minqlx.RET_STOP_ALL
        else:
            self.update_tag(player)
            self.take_from_queue(0.5)
            return minqlx.RET_STOP_ALL

    def cmd_queue_version(self, player, msg, channel):
        channel.reply('^7This server has installed ^2queue.py {} ^7ver. by ^3Melod^1e^3iro'.format(self.version))

    def handle_client_command(self, player, command):
        @minqlx.thread
        def handler():
            if command == "team s":
                if player in self.teams()['spectator']:
                    self.remove_from_queue(player)
                    if player not in self._queue:
                        self.center_print(player, "You are set to spectate only")

        handler()

    def handle_vote_ended(self, votes, vote, args, passed):
        if vote == "teamsize":
            self.take_from_queue(4)

    def handle_config_string(self, index, value):
        if not value:
            return

        elif 529 <= index < 529 + 64:
            try:
                player = self.player(index - 529)
            except minqlx.NonexistentPlayerError:
                return

            if player.steam_id in self._tags:
                tag = self._tags[player.steam_id]

                tag_key = _tag_key.format(player.steam_id)
                if tag_key in self.db:
                    if len(tag) > 0:
                        tag += ' '
                    tag += self.db[tag_key]

                cs = minqlx.parse_variables(value, ordered=True)
                cs["xcn"] = tag
                cs["cn"] = tag
                new_cs = "".join(["\\{}\\{}".format(key, cs[key]) for key in cs])
                return new_cs

    def cmd_show_queue(self, player, msg, channel):
        msg = "^7No one in queue."
        if self._queue:
            msg = "^1Queue^7 >> "
            count = 1
            for p in self._queue:
                msg += '{}^7({}) '.format(p.name, count)
                count += 1
        channel.reply(msg)

        if self._afk:
            msg = "^3Away^7 >> "
            for p in self._afk:
                msg += p.name + " "

            channel.reply(msg)

    def cmd_afk(self, player, msg, channel):
        if len(msg) > 1:
            if self.db.has_permission(player, self.get_cvar("qlx_queueSetAfkPermission", int)):
                guy = self.find_player(msg[1])[0]
                if self.set_afk(guy):
                    player.tell("^7Status for {} has been set to ^3AFK^7.".format(guy.name))
                    return minqlx.RET_STOP_ALL
                else:
                    player.tell("Couldn't set status for {} to AFK.".format(guy.name))
                    return minqlx.RET_STOP_ALL
        if self.set_afk(player):
            player.tell("^7Your status has been set to ^3AFK^7.")
        else:
            player.tell("^7Couldn't set your status to AFK.")

    def cmd_playing(self, player, msg, channel):
        self.remove_afk(player)
        self.update_tag(player)
        player.tell("^7Your status has been set to ^2AVAILABLE^7.")

    def cmd_team_size(self, playing, msg, channel):
        self.take_from_queue(0.5)

    def handle_console_print(self, text):
        if text.find('broadcast: print "The RED team is now locked') != -1:
            self.is_red_locked = True
        elif text.find('broadcast: print "The BLUE team is now locked') != -1:
            self.is_blue_locked = True
        elif text.find('broadcast: print "The RED team is now unlocked') != -1:
            self.is_red_locked = False
            self.take_from_queue(0.5)  # if cause errors maybe call that in next_frame
        elif text.find('broadcast: print "The BLUE team is now unlocked') != -1:
            self.is_blue_locked = False
            self.take_from_queue(0.5)

    # -----------------------------------------------------------------------------------
    def cmd_queue_push(self, player, msg, channel):
        self.take_from_queue()

    def cmd_queue_add(self, player, msg, channel):
        print(f'cmd_queue_add player: {player}, msg: {msg}')
        if len(msg) < 2:
            self.add_to_queue(player)

        try:
            i = int(msg[1])
            target_player = self.player(i)
            if not (0 <= i < 64) or not target_player:
                raise ValueError
        except ValueError:
            channel.reply("Invalid ID.")
            return

        self.add_to_queue(target_player)

    def cmd_queue_update(self, player, msg, channel):
        for p in self.players():
            self.update_tag(p)

    # -----------------------------------------------------------------------------------
