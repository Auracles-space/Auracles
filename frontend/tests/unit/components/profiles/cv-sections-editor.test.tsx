import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  EducationEditor,
  ExperienceEditor,
} from "@/components/modules/profiles/cv-sections-editor";
import type {
  ProfileEducation,
  ProfileExperience,
} from "@/lib/generated/types.gen";

describe("ExperienceEditor", () => {
  it("appends a blank entry when adding", () => {
    const onChange = vi.fn();
    render(<ExperienceEditor value={[]} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /add experience/i }));

    expect(onChange).toHaveBeenCalledWith([{ title: "", company: "" }]);
  });

  it("patches a single field by index", () => {
    const onChange = vi.fn();
    const value: ProfileExperience[] = [{ title: "", company: "" }];
    render(<ExperienceEditor value={value} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: "Principal" },
    });

    expect(onChange).toHaveBeenCalledWith([
      { title: "Principal", company: "" },
    ]);
  });

  it("toggles the current-role flag", () => {
    const onChange = vi.fn();
    const value: ProfileExperience[] = [{ title: "", company: "" }];
    render(<ExperienceEditor value={value} onChange={onChange} />);

    fireEvent.click(screen.getByRole("checkbox"));

    expect(onChange).toHaveBeenCalledWith([
      { title: "", company: "", current: true },
    ]);
  });

  it("removes an entry", () => {
    const onChange = vi.fn();
    const value: ProfileExperience[] = [{ title: "A", company: "X" }];
    render(<ExperienceEditor value={value} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /remove experience/i }));

    expect(onChange).toHaveBeenCalledWith([]);
  });
});

describe("EducationEditor", () => {
  it("appends a blank entry when adding", () => {
    const onChange = vi.fn();
    render(<EducationEditor value={[]} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /add education/i }));

    expect(onChange).toHaveBeenCalledWith([{ school: "" }]);
  });

  it("parses a valid start year into a number", () => {
    const onChange = vi.fn();
    const value: ProfileEducation[] = [{ school: "Unilag" }];
    render(<EducationEditor value={value} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("Start year"), {
      target: { value: "2010" },
    });

    expect(onChange).toHaveBeenCalledWith([
      { school: "Unilag", start_year: 2010 },
    ]);
  });

  it("stores null for a blank year", () => {
    const onChange = vi.fn();
    const value: ProfileEducation[] = [{ school: "Unilag" }];
    render(<EducationEditor value={value} onChange={onChange} />);

    fireEvent.change(screen.getByLabelText("End year"), {
      target: { value: "  " },
    });

    expect(onChange).toHaveBeenCalledWith([
      { school: "Unilag", end_year: null },
    ]);
  });

  it("removes an entry", () => {
    const onChange = vi.fn();
    const value: ProfileEducation[] = [{ school: "Unilag" }];
    render(<EducationEditor value={value} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: /remove education/i }));

    expect(onChange).toHaveBeenCalledWith([]);
  });
});
