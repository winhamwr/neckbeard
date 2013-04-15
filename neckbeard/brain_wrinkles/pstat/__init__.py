import os

from fabric.api import (
    hide,
    put,
    run,
    sudo,
)
from fabric.contrib.files import upload_template


def _files_are_identical(first_fp, second_fp):
    with hide('warnings'):
        result = sudo('diff -q %s %s' % (first_fp, second_fp))
    if result.return_code == 0:
        return True
    return False


def _mv_file_changed(start_path, end_path, use_sudo=False, mode=None):
    """
    Move a file to a location, optionally settings its mode and user, and
    return True if the file is new or different.
    """
    _, file_name = os.path.split(start_path)

    # Determine if the end is to a folder or to specific file
    is_folder = True
    _, end_tail = os.path.split(end_path)
    if end_tail:
        is_folder = False

    # If the end_path is a folder, we need to append the file name
    # to get the true final path of the end file
    end_full_path = end_path
    if is_folder:
        end_full_path = os.path.join(end_path, file_name)

    changed = not _files_are_identical(start_path, end_full_path)

    if changed:
        cmd = 'mv %s %s' % (start_path, end_full_path)
        if use_sudo:
            sudo(cmd)
            sudo('chown root:root %s' % end_full_path)
        else:
            run(cmd)

    if mode:
        sudo('chmod %o %s' % (mode, end_full_path))

    return changed


def upload_template_changed(
    local_file, remote_path, context=None, use_sudo=False,
    mode=None, use_jinja=False):
    """
    Do a put as root and return True if the remote_path is now actually
    different.
    """
    tpl_dir, file_name = os.path.split(os.path.abspath(local_file))
    assert file_name
    tmp_path = os.path.join('/tmp/', file_name)
    with hide('everything'):
        if use_jinja:
            upload_template(
                file_name,
                tmp_path,
                context=context,
                use_jinja=True,
                template_dir=tpl_dir)
        else:
            upload_template(
                local_file,
                tmp_path,
                context=context,
            )

    return _mv_file_changed(
        tmp_path, remote_path, use_sudo=use_sudo, mode=mode)


def put_changed(local_file, remote_path, use_sudo=False, mode=None):
    """
    Do a put as root and return True if the remote_path is now actually
    different.
    """
    _, file_name = os.path.split(local_file)
    assert file_name
    tmp_path = os.path.join('/tmp/', file_name)
    put(local_file, tmp_path)

    return _mv_file_changed(
        tmp_path, remote_path, use_sudo=use_sudo, mode=mode)
