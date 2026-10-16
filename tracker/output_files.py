"""Bounded output discovery shared by JSON and JSONL collectors."""
import fnmatch
import os
from pathlib import Path

from .schema import InputError


def matching_paths(watcher):
    paths = []
    def scan(directory, depth=0):
        if depth > 32:
            raise InputError('Output tree exceeds 32 levels; select a narrower root')
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                path = watcher._within(Path(entry.path), watcher.root)
                if entry.is_dir(follow_symlinks=False):
                    scan(path, depth + 1)
                elif entry.is_file(follow_symlinks=False) and fnmatch.fnmatchcase(entry.name, watcher.pattern):
                    paths.append(path)
                    if len(paths) > watcher.max_files:
                        raise InputError(f'More than {watcher.max_files} matching files; narrow the directory or pattern')
    scan(watcher.root)
    return sorted(paths)
