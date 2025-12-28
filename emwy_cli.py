#!/usr/bin/env python3

import argparse
import yaml
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
	parser.add_argument('-c', '--cache-dir', dest='cache_dir',
		help='directory for temporary render files')
	parser.add_argument('-k', '--keep-temp', dest='keep_temp',
		help='keep temporary render files', action='store_true')
	parser.add_argument('-K', '--no-keep-temp', dest='keep_temp',
		help='remove temporary render files', action='store_false')
	parser.add_argument('-p', '--dump-plan', dest='dump_plan', action='store_true',
		help='print compiled playlists after planning')
	parser.set_defaults(keep_temp=False)
	args = parser.parse_args()
	return args

#============================================

def main():
	args = parse_args()
	project = EmwyProject(args.yamlfile, output_override=args.output_file,
		dry_run=args.dry_run, keep_temp=args.keep_temp, cache_dir=args.cache_dir)
	if args.dump_plan:
		project.validate()
		plan = {
			'stack': project.stack,
			'playlists': project.playlists,
		}
		print(yaml.safe_dump(plan, sort_keys=False))
		return
	project.run()


if __name__ == '__main__':
	main()
