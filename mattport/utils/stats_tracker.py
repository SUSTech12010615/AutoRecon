"""
Stats tracker base class and functionality
"""
import datetime
import enum
import logging
from typing import Any, Dict

from omegaconf import DictConfig

from mattport.utils import comms
from mattport.utils.decorators import check_main_thread, check_print_stats_step, check_stats_enabled, decorate_all

STATS_TRACKER = []


def update_stats(args: Dict[str, Any]):
    """update global stats tracker based on arguments"""
    assert comms.is_main_process(), "Writing out with process other than main"
    if "value" in args:
        STATS_TRACKER[0].update_value(**args)
    elif "start_time" in args:
        STATS_TRACKER[0].update_time(**args)
    else:
        raise NotImplementedError


def print_stats(fraction_done: float):
    """print current statistics information"""
    assert comms.is_main_process(), "Writing out with process other than main"
    STATS_TRACKER[0].print_stats(fraction_done)


def setup_stats_tracker(config: DictConfig):
    """Initialization of stats tracker"""
    if comms.is_main_process():
        STATS_TRACKER.append(StatsTracker(config))


class Stats(enum.Enum):
    """Possible Stats values for StatsTracker

    Args:
        enum (_type_): _description_
    """

    ITER_LOAD_TIME = "Data Load (ms)"
    ITER_TRAIN_TIME = "Train Iter (ms)"
    TOTAL_TRAIN_TIME = "Train Total (time)"
    RAYS_PER_SEC = "Rays Per Sec (1/s)"
    CURR_TEST_PSNR = "Test PSNR"
    ETA = "ETA (time)"


@decorate_all([check_stats_enabled, check_main_thread])
class StatsTracker:
    """Stats Tracker class"""

    def __init__(self, config: DictConfig):
        self.config = config
        if self.config.logging.enable_stats:
            self.max_history = self.config.logging.stats_tracker.max_history
            self.step = 0
            self.stats_dict = {}
            self.past_stats = []
            self.new_key = False
            self.stats_to_track = set()
            for name in self.config.logging.stats_tracker.stats_to_track:
                self.stats_to_track.add(Stats[name])
            logging.info("Successfully set up StatsTracker")
        else:
            logging.info("StatsTracker disabled; enable in config.")

    def update_value(self, name: enum.Enum, value: float, step: int):
        """update stats dictionary with key value pair

        Args:
            name (enum.Enum): Enum name of statistic we are logging
            value (float): value to update.
            step (int): number of total iteration steps.
        """
        if name in self.stats_to_track:
            self.step = step
            self.new_key = not name in self.stats_dict or self.new_key
            self.stats_dict[name] = value

    def update_time(
        self, name: enum.Enum, start_time: float, end_time: float, step: int = None, batch_size: int = None
    ):
        """update the stats dictionary with running averages/cumulative durations

        Args:
            name (enum.Enum): Enum name of statistic we are logging
            start_time (float): start time for the call in seconds
            end_time (float): end time when the call finished executing in seconds
            step (int): number of total iteration steps. Defaults to None.
                if None, reports duration without averaging
            batch_size (int, optional): total number of rays in a batch;
                if None, reports duration instead of batch per second. Defaults to None.
        """
        if name in self.stats_to_track:
            self.step = step
            self.new_key = not name in self.stats_dict or self.new_key
            val = end_time - start_time
            if batch_size:
                # calculate the batch per second stat
                val = batch_size / val

            if step is not None:
                # calculate updated average over the buffered max history
                curr_history = self.stats_dict.get(name, {"buffer": [], "avg": 0})
                curr_buffer = curr_history["buffer"]
                curr_avg = curr_history["avg"]
                if len(curr_buffer) >= self.max_history:
                    curr_buffer.pop(0)
                curr_buffer.append(val)
                curr_avg = sum(curr_buffer) / len(curr_buffer)
                self.stats_dict[name] = {"buffer": curr_buffer, "avg": curr_avg}
            else:
                # logging total time instead of average
                self.stats_dict[name] = val

            if name == Stats.ITER_TRAIN_TIME and Stats.ETA in self.stats_to_track:
                # update ETA if logging iteration train time
                remain_iter = self.config.graph.max_num_iterations - step
                self.stats_dict[Stats.ETA] = remain_iter * self.stats_dict[name]["avg"]

    def handle_header(self):
        """helper to handle the printing of the header labels"""
        if self.step == 0 or self.new_key:
            mssg = f"{'Step (% Done)':<20}"
            for k in self.stats_dict:
                mssg += f"{k.value:<20} "
            if self.step > 0:
                cursorup(len(self.past_stats) + 2)
            print(mssg)
            print("-" * len(mssg))
            if self.step > 0:
                for mssg in self.past_stats:
                    print(mssg)

    def handle_stats(self, fraction_done):
        """helper to print out the stats in a readable format"""
        if self.step > 0:
            curr_mssg = f"{self.step} ({fraction_done*100:.02f}%)"
            curr_mssg = f"{curr_mssg:<20}"
            for k, v in self.stats_dict.items():
                if isinstance(v, dict):
                    v = v["avg"]

                if "(time)" in k.value:
                    v = str(datetime.timedelta(seconds=v))
                elif "(ms)" in k.value:
                    ms = v * 1e3
                    v = f"{ms:0.4f}"
                else:
                    v = f"{v:0.4f}"
                curr_mssg += f"{v:<20} "
            # update the history buffer
            # if len(self.past_stats) >= self.max_history:
            #     self.past_stats.pop(0)
            # cursorup(len(self.past_stats) + 1)
            # for mssg in self.past_stats:
            #     print(mssg)
            print(curr_mssg)
            # self.past_stats.append(curr_mssg)

    @check_print_stats_step
    def print_stats(self, fraction_done: float):
        """helper to print out the stats dictionary.

        Args:
            fraction_done (float): fraction of steps executed in training iterations
        """
        # print a new header line if there is a new key added
        # self.handle_header()

        # generate a new stats reporting message
        self.handle_stats(fraction_done)

    def dump_stats(self):
        """Dump stats locally to a json file"""
        raise NotImplementedError


def cursorup(x: int):
    """utility tool to move the cursor up on the terminal

    Args:
        x (int): amount of lines to move cursor upward
    """
    print(f"\r\033[{x}A", end="")
