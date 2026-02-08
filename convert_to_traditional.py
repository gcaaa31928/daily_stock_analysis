#!/usr/bin/env python3
"""
简体转繁体批量转换脚本
使用 OpenCC 将项目中所有简体中文转换为繁体中文（台湾标准）
"""

import os
import sys
from pathlib import Path
from opencc import OpenCC

# 初始化 OpenCC 转换器（简体到台湾繁体）
cc = OpenCC('s2tw')

def should_skip_file(file_path: str) -> bool:
    """判断是否应该跳过该文件"""
    skip_patterns = [
        '__pycache__',
        '.git',
        'node_modules',
        '.venv',
        'venv',
        '.pyc',
        'convert_to_traditional.py',  # 跳过自己
        '.egg-info',
        'dist',
        'build',
    ]
    return any(pattern in file_path for pattern in skip_patterns)

def convert_file(file_path: Path):
    """转换单个文件"""
    try:
        # 读取文件
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 转换为繁体
        converted_content = cc.convert(content)

        # 如果内容有变化，才写入
        if content != converted_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(converted_content)
            print(f"✅ 已转换: {file_path}")
            return True
        else:
            print(f"⏭️  无需转换: {file_path}")
            return False
    except Exception as e:
        print(f"❌ 转换失败 {file_path}: {e}")
        return False

def main():
    """主函数"""
    project_root = Path(__file__).parent

    # 需要转换的文件扩展名
    extensions = ['.py', '.md', '.txt', '.yml', '.yaml', '.sh', '.env.example']

    converted_count = 0
    total_count = 0

    print("🔄 开始批量转换简体为繁体...")
    print(f"📁 项目根目录: {project_root}")
    print("=" * 80)

    # 遍历所有文件
    for ext in extensions:
        for file_path in project_root.rglob(f"*{ext}"):
            # 跳过不需要转换的文件
            if should_skip_file(str(file_path)):
                continue

            total_count += 1
            if convert_file(file_path):
                converted_count += 1

    print("=" * 80)
    print(f"🎉 转换完成！")
    print(f"📊 共检查 {total_count} 个文件，成功转换 {converted_count} 个文件")

if __name__ == "__main__":
    main()
