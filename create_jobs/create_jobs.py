#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2017 Ben Lindsay <benjlindsay@gmail.com>

from os import popen, makedirs, walk, system, rename
from os.path import join, isfile, isdir, basename, dirname, exists
import numpy as np
import pandas as pd
import time
import string
import sys

_PY2 = sys.version_info[0] == 2
if not _PY2:
    basestring = str


def create_jobs(file_list=None, file_copy_list=None, file_common_list=None, param_table=None, base_dir='.',
                table_sep='\s+', sub_file='sub.sh', sub_prog=None, sub_cluster='rrlogin', command_file='commandlines', n_cores_per_job=1,
                sleep_time=0, submit=True):
    """
    Recursively generate the directory tree specified by values in files or
    functions from 'tier_list'. Copies the files in 'file_list' to each
    job directory and replaces all the variables with appropriate values
    """
    # Check variables
    if file_list is None:
        raise ValueError("No file_list provided")
    if param_table is None:
        raise ValueError("No param_table provided")
    if isinstance(param_table, pd.DataFrame):
        param_df = param_table
    elif isinstance(param_table, basestring):
        if isfile(param_table):
            param_df = pd.read_csv(param_table, sep=table_sep)
        else:
            raise ValueError(
                "{} is not a valid file name!".format(param_table))
    elif isinstance(param_table, dict):
        param_df = pd.DataFrame(param_table)
    else:
        raise ValueError("param_table must be either a pandas DataFrame " +
                         "or a file name!")
    if sub_prog is None:
        sub_prog = _find_sub_prog()

    # Create JOB_NAME column if not already there
    if not 'JOB_NAME' in param_df.columns:
        job_name_col = None
        for c in param_df.columns:
            if np.all(~param_df[c].duplicated()):
                job_name_col = c
                break
        if job_name_col is None:
            param_df['JOB_NAME'] = param_df.index
        else:
            param_df['JOB_NAME'] = param_df[job_name_col]

    command_lines = ""

    # Iterate over rows of dataframe, creating and submitting jobs
    param_dict_list = param_df.to_dict(orient='records')
    for param_dict in param_dict_list:
        job_dir = join(base_dir, str(param_dict['JOB_NAME']))
        if isdir(job_dir):
            print('{} already exists. Skipping.'.format(job_dir))
            continue
        else:
            makedirs(job_dir)
        if 'stampede' in sub_cluster:
            if command_lines == "":
                sub_file_dict = param_dict
            command_lines += "cd " + basename(job_dir) + "; " + str(param_dict['ssubmit_command']) + "\n"
        else:
            if not sub_file in file_list:
                file_list.append(sub_file)
        _copy_files(file_copy_list, job_dir)
        _copy_and_replace_files(file_list, job_dir, param_dict)

        if 'stampede' not in sub_cluster:
            if submit:
                sub_file = _replace_vars(sub_file, param_dict)
                _submit_job(job_dir, sub_file, sleep_time, sub_prog)

    if 'stampede' in sub_cluster:
        if submit:
            sub_file_dict.update({"n_jobs": len(
            param_dict_list) * n_cores_per_job + 1, "commandlines": command_lines})
            sub_file = _replace_vars(sub_file, sub_file_dict)
            file_sub_list = [sub_file, command_file]
            _copy_and_replace_files(file_sub_list, base_dir, sub_file_dict)
            _submit_job(base_dir, sub_file, sleep_time, sub_prog)
    
    _copy_files(file_common_list, base_dir)


def _find_sub_prog():
    """
    Returns the first job submission command found on the system.
    Currently, only qsub and sbatch are supported
    """
    possible_sub_prog_list = ['sbatch', 'qsub']
    for prog in possible_sub_prog_list:
        if popen('command -v ' + prog).read() != '':
            return prog
    raise ValueError("Could not find any of the following programs: {}",
                     possible_sub_prog_list)


def _copy_files(file_copy_list, job_dir):
    """
    Given a list, `file_copy_list`, whose members are either file paths or
    tuples like `('/path/to/from_file_name', 'to_file_name')` and job directory
    `job_dir`, copies the files to the job directory and replaces
    variables in those files and in the file names.
    """
    print("Copying files/ folders to {}".format(job_dir))
    for input_file in file_copy_list:
        if isinstance(input_file, basestring):
            if isdir(input_file):
                file_copy_list.remove(input_file)
                dirs = [dirs for root, dirs, files in walk(input_file)]
                if (dirs[0] != []):
                    dirs = [(join(input_file, dir), join(
                        basename(input_file), dir)) for dir in dirs[0]]
                    file_copy_list += dirs
                files = [files for root, dirs, files in walk(input_file)]
                if (files[0] != []):
                    files = [(join(input_file, file), join(
                        basename(input_file), file)) for file in files[0]]
                    file_copy_list += files
                _copy_files(file_copy_list, job_dir)
                return
            elif isfile(input_file):
                from_file = input_file
                to_file = join(job_dir, basename(input_file))
            else:
                raise ValueError(
                    "file_copy_list cannot have non-existent files")
        elif isinstance(input_file, tuple):
            if isdir(input_file[0]):
                file_copy_list.remove(input_file)
                dirs = [dirs for root, dirs, files in walk(input_file[0])]
                if (dirs[0] != []):
                    dirs = [(join(input_file[0], dir), join(input_file[1], dir))
                            for dir in dirs[0]]
                    file_copy_list += dirs
                files = [files for root, dirs, files in walk(input_file[0])]
                if (files[0] != []):
                    files = [(join(input_file[0], file), join(
                        input_file[1], file)) for file in files[0]]
                    file_copy_list += files
                _copy_files(file_copy_list, job_dir)
                return
            elif isfile(input_file[0]):
                from_file = input_file[0]
                to_file = join(job_dir, input_file[1])
            else:
                raise ValueError(
                    "file_copy_list cannot have tuples such as these (folder, file) or (file, folder)")
        else:
            raise ValueError("file_copy_list invalid")

        if not exists(dirname(to_file)):
            makedirs(dirname(to_file))
        # Copy file to job_dir
        system("cp " + from_file + " " + to_file)
        """ with open(from_file, 'r') as f_in, \
                open(to_file, 'w') as f_out:
            text = f_in.read()
            f_out.write(text) """


def _copy_and_replace_files(file_list, job_dir, param_dict):
    """
    Given a list, `file_list`, whose members are either file paths or
    tuples like `('/path/to/from_file_name', 'to_file_name')` and job directory
    `job_dir`, copies the files to the job directory and replaces
    variables in those files and in the file names.
    """
    print("Copying files/ folders to {} and replacing vars".format(job_dir))
    for input_file in file_list:
        if isinstance(input_file, basestring):
            if isdir(input_file):
                file_list.remove(input_file)
                dirs = [dirs for root, dirs, files in walk(input_file)]
                if (dirs[0] != []):
                    dirs = [(join(input_file, dir), join(
                        basename(input_file), dir)) for dir in dirs[0]]
                    file_list += dirs
                files = [files for root, dirs, files in walk(input_file)]
                if (files[0] != []):
                    files = [(join(input_file, file), join(
                        basename(input_file), file)) for file in files[0]]
                    file_list += files
                _copy_and_replace_files(file_list, job_dir, param_dict)
                return
            elif isfile(input_file):
                from_file = input_file
                to_file = join(job_dir, basename(input_file))
            else:
                raise ValueError("file_list cannot have non-existent files")
        elif isinstance(input_file, tuple):
            if isdir(input_file[0]):
                file_list.remove(input_file)
                dirs = [dirs for root, dirs, files in walk(input_file[0])]
                if (dirs[0] != []):
                    dirs = [(join(input_file[0], dir), join(input_file[1], dir))
                            for dir in dirs[0]]
                    file_list += dirs
                files = [files for root, dirs, files in walk(input_file[0])]
                if (files[0] != []):
                    files = [(join(input_file[0], file), join(
                        input_file[1], file)) for file in files[0]]
                    file_list += files
                _copy_and_replace_files(file_list, job_dir, param_dict)
                return
            elif isfile(input_file[0]):
                from_file = input_file[0]
                to_file = join(job_dir, input_file[1])
            else:
                raise ValueError(
                    "file_list cannot have tuples such as these (folder, file) or (file, folder)")
        else:
            raise ValueError("file_list invalid")

        # Replace variables in file names, if any
        from_file = _replace_vars(from_file, param_dict)
        if not exists(dirname(to_file)):
            makedirs(dirname(to_file))
        to_file = _replace_vars(to_file, param_dict)
        # Copy file to job_dir with variables in text of file replaced
        with open(from_file, 'r') as f_in, \
                open(to_file, 'w') as f_out:
            text = f_in.read()
            text = _replace_vars(text, param_dict)
            f_out.write(text)


def _replace_vars(text, param_dict):
    """
    Given a block of text, replace any instances of '{key}' with 'value'
    if param_dict contains 'key':'value' pair.
    This is done safely so that brackets in a file don't cause an error if
    they don't contain a variable we want to replace.
    See http://stackoverflow.com/a/17215533/2680824

    Examples:
        >>> _replace_vars('{last}, {first} {last}', {'first':'James', 'last':'Bond'})
        'Bond, James Bond'
        >>> _replace_vars('{last}, {first} {last}', {'last':'Bond'})
        'Bond, {first} Bond'
    """
    # Handle the edge case where a '{}' in text breaks things.
    if '{}' in text:
        text = text.replace('{}', '__dummy__')
        contains_empty_brackets = True
    else:
        contains_empty_brackets = False

    # TODO: Handle case where there are invalid characters inside brackets

    # Run the string formatter
    text = string.Formatter().vformat(text, (), _Safe_Dict(param_dict))

    # Put empty brackets back in if they were there originally
    if contains_empty_brackets:
        text = text.replace('__dummy__', '{}')

    return text


class _Safe_Dict(dict):
    """
    Class with all the same functionality of a dictionary but if a key isn't
    present, it just returns '{key}'.
    This helps with _replace_vars().

    Examples:
        >>> d = _Safe_Dict({'last':'Bond'})
        >>> d['last']
        'Bond'
        >>> d['first']
        '{first}'
    """

    def __missing__(self, key):
        return '{' + key + '}'


def _submit_job(job_dir, sub_file, sleep_time, sub_prog):
    """
    Submit 'sub_file' in 'job_dir' using submission program 'sub_prog'.
    Wait 'sleep_time' seconds between each submission.
    """
    print("submitting {}".format(join(job_dir, basename(sub_file))))
    cmd = 'cd ' + job_dir + '; ' + sub_prog + \
        ' ' + basename(sub_file) + '; cd -'
    output = popen(cmd).read()
    print(output)
    if sleep_time > 0:
        time.sleep(sleep_time)