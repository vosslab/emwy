#!/usr/bin/env python3

import argparse
from emwylib.core.project import EmwyProject

#============================================

def parse_args():
	"""
	Parse command-line arguments.
	"""
	parser = argparse.ArgumentParser(description="CLI Movie Editor")
	parser.add_argument('-y', '--yaml', dest='yamlfile', required=True,
		help='main yaml file that outlines the processing to do')
	parser.add_argument('-o', '--output', dest='output_file',
		help='override output file from yaml')
	parser.add_argument('-n', '--dry-run', dest='dry_run', action='store_true',
		help='validate only, do not render')
	args = parser.parse_args()
	return args

#============================================

def main():
	args = parse_args()
	project = EmwyProject(args.yamlfile, output_override=args.output_file,
		dry_run=args.dry_run)
	project.run()


if __name__ == '__main__':
	main()
