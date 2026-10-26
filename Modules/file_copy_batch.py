#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
file_copy_batch.py

批量复制文件/目录模块。

支持：
1. 文件复制到目标目录；
2. 文件夹递归复制到目标目录；
3. 复制前清空目标目录或目标文件；
4. 批量任务；
5. 单个任务失败不中断整批任务；
6. 额外目录自动创建。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Union

PathLike = Union[str, Path]


@dataclass
class CopyTask:
    """
    单个复制任务。

    参数：
        source:
            源文件或源目录。

        target:
            目标目录。
            如果 source 是文件，默认会把文件复制到 target 目录下，保持原文件名。
            如果 source 是目录，默认会把 source 目录结构复制到 target 目录下。

        clean_target:
            复制前是否清理目标。
            - 如果 source 是目录：会删除整个 target 目录后重新复制。
            - 如果 source 是文件：只会删除目标目录下同名的目标文件，不会删除整个目标目录。

        recursive:
            source 为目录时，是否递归复制子目录和子文件。
            True：递归复制整个目录树。
            False：只复制源目录第一层文件，不复制子目录。

        overwrite:
            是否覆盖已存在的目标文件。
            True：覆盖。
            False：已存在则跳过。

        target_is_dir:
            target 是否视为目录。
            True：target 作为目录处理，文件会复制到该目录下。
            False：target 作为目标文件完整路径处理，仅适合文件复制场景。
    """

    source: PathLike
    target: PathLike
    clean_target: Optional[bool] = None
    recursive: Optional[bool] = None
    overwrite: Optional[bool] = None
    target_is_dir: Optional[bool] = None


@dataclass
class CopyResult:
    """单个任务的复制结果。"""

    source: str
    target: str
    success: bool
    message: str = ""


def _is_subpath(child: Path, parent: Path) -> bool:
    """判断 child 是否是 parent 的子路径。"""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _copy_tree_no_overwrite(src: Path, dst: Path) -> None:
    """
    递归复制目录树，但不覆盖已存在的文件。
    """
    dst.mkdir(parents=True, exist_ok=True)

    for item in src.iterdir():
        target = dst / item.name

        if item.is_dir():
            _copy_tree_no_overwrite(item, target)
        elif item.is_file():
            if not target.exists():
                shutil.copy2(item, target)


def _copy_directory(
    src: Path,
    dst: Path,
    recursive: bool,
    clean_target: bool,
    overwrite: bool,
) -> None:
    """
    复制目录。

    src:
        源目录。
    dst:
        目标目录。
    recursive:
        是否递归复制子目录。
    clean_target:
        是否复制前删除目标目录。
    overwrite:
        是否覆盖已有文件。
    """

    # 如果要求清理目标，则先删除目标目录
    if clean_target and dst.exists():
        if not dst.is_dir():
            raise FileExistsError(f"目标路径不是目录，无法整体清空: {dst}")
        shutil.rmtree(dst)

    # 确保目标目录存在
    dst.mkdir(parents=True, exist_ok=True)

    if recursive:
        if overwrite:
            # Python 3.8+ 支持 dirs_exist_ok=True
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            _copy_tree_no_overwrite(src, dst)
    else:
        # 非递归模式：只复制源目录第一层文件，不复制子目录
        for item in src.iterdir():
            if item.is_file():
                target_file = dst / item.name

                if target_file.exists() and not overwrite:
                    continue

                shutil.copy2(item, target_file)


def _copy_file(
    src: Path,
    dst: Path,
    clean_target: bool,
    overwrite: bool,
    target_is_dir: bool,
) -> None:
    """
    复制文件。

    src:
        源文件。
    dst:
        目标路径。
    clean_target:
        是否删除已存在的目标文件。
    overwrite:
        是否覆盖已存在的目标文件。
    target_is_dir:
        True：dst 作为目标目录，文件名保持不变。
        False：dst 作为目标文件完整路径。
    """

    if target_is_dir:
        dst.mkdir(parents=True, exist_ok=True)
        dst_file = dst / src.name
    else:
        if dst.is_dir():
            raise ValueError(f"target_is_dir=False，但目标是已存在目录: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst_file = dst

    # 文件任务的 clean_target 只删除同名目标文件，不删除整个目标目录
    if clean_target and dst_file.exists():
        if dst_file.is_dir():
            raise FileExistsError(f"目标文件路径是目录: {dst_file}")
        dst_file.unlink()

    if dst_file.exists() and not overwrite:
        return

    shutil.copy2(src, dst_file)


def _normalize_task(
    task,
    default_clean_target: bool,
    default_recursive: bool,
    default_overwrite: bool,
    default_target_is_dir: bool,
) -> Tuple[PathLike, PathLike, bool, bool, bool, bool]:
    """
    将不同形式的任务统一转换为：
    (source, target, clean_target, recursive, overwrite, target_is_dir)
    """

    # CopyTask 对象
    if isinstance(task, CopyTask):
        return (
            task.source,
            task.target,
            default_clean_target if task.clean_target is None else task.clean_target,
            default_recursive if task.recursive is None else task.recursive,
            default_overwrite if task.overwrite is None else task.overwrite,
            default_target_is_dir if task.target_is_dir is None else task.target_is_dir,
        )

    # 字典形式
    if isinstance(task, dict):
        source = task.get("source", task.get("src"))
        target = task.get("target", task.get("dst", task.get("target_dir")))

        if source is None or target is None:
            raise ValueError(f"字典任务必须包含 source/src 和 target/dst/target_dir: {task}")

        clean_target = task.get("clean_target")
        recursive = task.get("recursive")
        overwrite = task.get("overwrite")
        target_is_dir = task.get("target_is_dir")

        return (
            source,
            target,
            default_clean_target if clean_target is None else bool(clean_target),
            default_recursive if recursive is None else bool(recursive),
            default_overwrite if overwrite is None else bool(overwrite),
            default_target_is_dir if target_is_dir is None else bool(target_is_dir),
        )

    # 元组或列表形式
    if isinstance(task, (tuple, list)):
        # (source, target)
        if len(task) == 2:
            return (
                task[0],
                task[1],
                default_clean_target,
                default_recursive,
                default_overwrite,
                default_target_is_dir,
            )

        # (source, target, clean_target, recursive, overwrite)
        if len(task) == 5:
            return (
                task[0],
                task[1],
                bool(task[2]),
                bool(task[3]),
                bool(task[4]),
                default_target_is_dir,
            )

        # (source, target, clean_target, recursive, overwrite, target_is_dir)
        if len(task) == 6:
            return (
                task[0],
                task[1],
                bool(task[2]),
                bool(task[3]),
                bool(task[4]),
                bool(task[5]),
            )

        raise ValueError(
            "列表/元组任务必须是以下格式之一：\n"
            "(source, target)\n"
            "(source, target, clean_target, recursive, overwrite)\n"
            "(source, target, clean_target, recursive, overwrite, target_is_dir)"
        )

    raise TypeError(f"不支持的任务类型: {type(task)!r}")


def batch_copy(
    tasks: Iterable[Union[CopyTask, Dict[str, object], Tuple[PathLike, PathLike], List[PathLike]]],
    *,
    clean_target: bool = False,
    recursive: bool = True,
    overwrite: bool = True,
    target_is_dir: bool = True,
    extra_dirs: Optional[Iterable[PathLike]] = None,
    raise_on_error: bool = False,
    verbose: bool = True,
) -> List[CopyResult]:
    """
    批量复制入口。

    参数：
        tasks:
            任务列表，支持多种格式：

            1. CopyTask 对象列表：
               [
                   CopyTask(source_path, target_path, clean_target=True),
               ]

            2. 元组列表：
               [
                   (source_path, target_path),
               ]

            3. 字典列表：
               [
                   {
                       "source": source_path,
                       "target": target_path,
                       "clean_target": True,
                       "recursive": True,
                       "overwrite": True,
                   },
               ]

        clean_target:
            默认是否复制前清理目标。
            对目录任务：删除整个目标目录。
            对文件任务：只删除目标目录中的同名文件。

        recursive:
            目录复制时是否递归复制子目录，默认 True。

        overwrite:
            是否覆盖已有文件，默认 True。

        target_is_dir:
            是否把 target 视为目录，默认 True。

        extra_dirs:
            额外需要创建的目录列表。
            例如原来的 target_path_data、target_path_1。

        raise_on_error:
            True：某个任务失败时立即抛出异常。
            False：某个任务失败时继续执行后续任务。

        verbose:
            是否打印过程信息。

    返回：
        List[CopyResult]
        每个任务一个结果对象。
    """

    # 如果用户直接传入单个 (source, target)，自动包装成列表
    if isinstance(tasks, (tuple, list)) and len(tasks) == 2:
        first, second = tasks
        if not isinstance(first, (tuple, list, dict, CopyTask)) and not isinstance(
            second, (tuple, list, dict, CopyTask)
        ):
            tasks = [tasks]

    task_list = list(tasks)
    results: List[CopyResult] = []

    # 提前创建额外目录
    extra_dir_list = [Path(extra_dir).expanduser() for extra_dir in (extra_dirs or [])]
    for extra_path in extra_dir_list:
        extra_path.mkdir(parents=True, exist_ok=True)
        if verbose:
            print(f"目录已就绪: {extra_path}")

    for idx, task in enumerate(task_list, start=1):
        source_raw = ""
        target_raw = ""

        try:
            (
                source_raw,
                target_raw,
                task_clean_target,
                task_recursive,
                task_overwrite,
                task_target_is_dir,
            ) = _normalize_task(
                task,
                clean_target,
                recursive,
                overwrite,
                target_is_dir,
            )

            src = Path(str(source_raw)).expanduser()
            dst = Path(str(target_raw)).expanduser()

            if not src.exists():
                raise FileNotFoundError(f"源路径不存在: {src}")

            src_res = src.resolve()
            dst_res = dst.resolve()

            if src_res == dst_res:
                raise ValueError("源路径和目标路径相同")

            if src.is_dir():
                # 目录复制
                if _is_subpath(dst_res, src_res):
                    raise ValueError(f"目标目录不能位于源目录内部: {dst_res}")

                _copy_directory(
                    src=src,
                    dst=dst,
                    recursive=task_recursive,
                    clean_target=task_clean_target,
                    overwrite=task_overwrite,
                )
                message = "目录复制成功"

            else:
                # 文件复制
                _copy_file(
                    src=src,
                    dst=dst,
                    clean_target=task_clean_target,
                    overwrite=task_overwrite,
                    target_is_dir=task_target_is_dir,
                )
                message = "文件复制成功"

            results.append(
                CopyResult(
                    source=str(src),
                    target=str(dst),
                    success=True,
                    message=message,
                )
            )

            if verbose:
                print(f"[{idx}/{len(task_list)}] {message}: {src} -> {dst}")

        except Exception as exc:
            results.append(
                CopyResult(
                    source=str(source_raw),
                    target=str(target_raw),
                    success=False,
                    message=str(exc),
                )
            )

            if verbose:
                print(
                    f"[{idx}/{len(task_list)}] 复制失败: {source_raw} -> {target_raw}，原因: {exc}"
                )

            if raise_on_error:
                raise

    # 复制完成后再次确保额外目录存在。
    # 防止某些 clean_target 任务删除了额外目录。
    for extra_path in extra_dir_list:
        extra_path.mkdir(parents=True, exist_ok=True)

    success_count = sum(1 for item in results if item.success)

    if verbose:
        print(f"批量复制完成: 成功 {success_count}/{len(results)}")

    return results


def batch_copy_from_lists(
    sources: Iterable[PathLike],
    targets: Iterable[PathLike],
    **kwargs,
) -> List[CopyResult]:
    """
    通过两个列表批量复制：

    sources:
        源文件/源目录列表。
    targets:
        目标目录列表，必须与 sources 一一对应。

    示例：
        sources = [file1, dir2]
        targets = [target1, target2]
        batch_copy_from_lists(sources, targets)
    """

    source_list = list(sources)
    target_list = list(targets)

    if len(source_list) != len(target_list):
        raise ValueError(
            f"sources 和 targets 数量不一致: sources={len(source_list)}, targets={len(target_list)}"
        )

    tasks = list(zip(source_list, target_list))
    return batch_copy(tasks, **kwargs)




'''
##################调用方法
1、删除 a1 后复制 a -> a1,删除 b1 后复制 b -> b1,删除 c1 后复制 c -> c1

from file_copy_batch import batch_copy, CopyTask

tasks = [
    CopyTask(source=r"D:\\data\\a", target=r"D:\\data\\a1", clean_target=True),
    CopyTask(source=r"D:\\data\\b", target=r"D:\\data\\b1", clean_target=True),
    CopyTask(source=r"D:\\data\\c", target=r"D:\\data\\c1", clean_target=True),
]

batch_copy(tasks)

2、用两个列表分别传入源目录和目标目录

from file_copy_batch import batch_copy_from_lists

sources = [
    r"D:\\data\\a",
    r"D:\\data\\b",
    r"D:\\data\\c",
]

targets = [
    r"D:\\data\\a1",
    r"D:\\data\\b1",
    r"D:\\data\\c1",
]

batch_copy_from_lists(
    sources,
    targets,
    clean_target=False,
    recursive=True,
    overwrite=True,
)

3、使用元组列表复制
from file_copy_batch import batch_copy

tasks = [
    (r"D:\\data\\a", r"D:\\data\\a1"),
    (r"D:\\data\\b", r"D:\\data\\b1"),
    (r"D:\\data\\c", r"D:\\data\\c1"),
]

batch_copy(
    tasks,
    clean_target=False,   # 不删除目标目录
    recursive=True,       # 递归复制子目录和文件
    overwrite=True,       # 覆盖已有文件
    target_is_dir=True,   # 目标按目录处理
)

4、只创建目标目录
# 如果只是想创建目标目录，不进行复制，可以直接用模块里的 extra_dirs 参数，并把任务列表传空。

from file_copy_batch import batch_copy

target_dirs = [
    r"D:\\data\\a1",
    # r"D:\\data\\b1",
]

batch_copy(
    [],                 # 空任务列表，表示不复制任何文件/目录
    extra_dirs=target_dirs,
    verbose=True
)

##################
'''