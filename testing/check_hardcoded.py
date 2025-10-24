#!/usr/bin/env python3
import ast
import os
from pathlib import Path

SUSPICIOUS_PATTERNS = ['api_key', 'password', 'secret', 'token', 'https://', 'http://']

class HardcodedDetector(ast.NodeVisitor):
    def __init__(self):
        self.issues = []
    
    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                var_name = target.id.lower()
                value = str(node.value.value)
                
                # Detectar patrones sospechosos
                if any(p in var_name for p in SUSPICIOUS_PATTERNS):
                    self.issues.append((node.lineno, target.id, value))
                elif any(p in value for p in ['http://', 'https://']):
                    self.issues.append((node.lineno, target.id, value))
        
        self.generic_visit(node)

def check_file(filepath):
    with open(filepath, 'r') as f:
        tree = ast.parse(f.read())
        detector = HardcodedDetector()
        detector.visit(tree)
        return detector.issues

def main():
    print("\n🔎 Detectando valores hardcodeados...")
    
    all_issues = {}
    for lambda_dir in Path('lambdas').iterdir():
        if lambda_dir.is_dir():
            handler = lambda_dir / 'handler.py'
            if handler.exists():
                issues = check_file(handler)
                if issues:
                    all_issues[lambda_dir.name] = issues
    
    if not all_issues:
        print("   ✅ No se encontraron valores hardcodeados")
        return 0
    
    print("   ⚠️  Valores sospechosos encontrados:\n")
    for lambda_name, issues in all_issues.items():
        print(f"   📁 {lambda_name}:")
        for line, var, value in issues:
            print(f"      Línea {line}: {var} = {value[:50]}...")
    
    return 1

if __name__ == '__main__':
    exit(main())