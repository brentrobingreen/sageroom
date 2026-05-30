-- Seed the launch brain library
-- Run after 001_initial.sql

insert into public.brains (slug, display_name, tagline, category) values
  ('tony_robbins',  'Tony Robbins',   'Peak performance, psychology & wealth strategies',  'performance'),
  ('warren_buffett','Warren Buffett',  'Value investing, business quality & long-term thinking', 'investing'),
  ('robin_sharma',  'Robin Sharma',   'Leadership mastery, mindfulness & personal greatness', 'philosophy'),
  ('steve_jobs',    'Steve Jobs',     'Product vision, creative leadership & simplicity',   'innovation');
